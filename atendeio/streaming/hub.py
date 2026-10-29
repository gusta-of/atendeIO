"""CameraHub: leitura + YOLO + JPEG de UMA câmera, distribuídos aos espectadores.

Uma thread lê o dispositivo o mais rápido que ele entrega (guardando só o frame
mais recente); outra roda a inferência e o JPEG uma vez por frame. O custo não
cresce com o número de abas abertas. Reconecta sozinho se a câmera cair."""

import asyncio
import contextlib
import threading
import time
from typing import Callable, Iterable, Optional

import cv2

from ..analytics.flow import FlowAggregator
from ..analytics.people import PeopleCounter
from ..analytics.tracker import PersonTracker
from ..analytics.zones import AnalyticsConfig, Zone, ZoneAnalyzer
from ..config import Settings
from ..vision.detector import Detector
from ..vision.areas_draw import draw_areas
from ..vision.draw import draw_detections
from ..vision.inventory import summarize
from ..vision.sources import open_source
from .events import (SNAPSHOT_EVERY_S, EventBus, counts_of, diff_counts, diff_states, frame_of,
                     snapshot_of)


def _put_latest(q: asyncio.Queue, item) -> None:
    """Fila de 1: o espectador lento pula frames, sem acumular atraso."""
    if q.full():
        with contextlib.suppress(asyncio.QueueEmpty):
            q.get_nowait()
    with contextlib.suppress(asyncio.QueueFull):
        q.put_nowait(item)


class CameraHub:
    def __init__(self, cam_id: int, owner_id: int, get_source: Callable, detector: Detector,
                 settings: Settings, zones: Iterable[Zone] = (), enabled: bool = True,
                 classes: Optional[frozenset] = None, flow_sink: Optional[Callable[[dict], object]] = None):
        """`get_source()` é chamado a cada (re)conexão: credenciais não ficam em atributo.
        `flow_sink(lote)` recebe o histórico de fluxo agregado (nunca bloqueia: é a fila do FlowWriter)."""
        self.cam_id, self.owner_id = cam_id, owner_id
        self.fps_view: Optional[float] = None      # FPS por câmera (None = padrão do sistema)
        self.fps_monitor: Optional[float] = None
        self.map_pin = False          # preso pelo Mapa do ambiente (lido em FPS de monitoramento, sem contar como espectador)
        self.monitor = False          # monitoramento contínuo: o hub fica de pé mesmo sem ninguém assistindo
        self._wake = threading.Event()  # acorda a espera entre quadros (novo espectador, parada)
        self._flow = FlowAggregator(cam_id, settings.flow_flush_s)
        self._flow_sink = flow_sink
        self._last_flow_sample = 0.0
        self._get_source, self._detector, self._cfg = get_source, detector, settings
        self.stop_event = threading.Event()
        self.ready = threading.Event()
        self.online = False
        self.viewers = 0
        self.idle_since = time.monotonic()

        self._cv = threading.Condition()
        self._frame, self._fid = None, 0

        self._pub_lock = threading.Lock()
        self._subs = []
        self._fsubs = []   # espectadores NATIVOS (app desktop): recebem o quadro BGR direto, sem JPEG nem asyncio
        # Reconhecimento: chave geral + classes (None = todas, só em uso direto/testes; a API sempre passa a lista salva)
        self._recognition = (bool(enabled), None if classes is None else frozenset(classes))
        self.state = {**summarize([]), "areas": [], "people": 0, "size": None,
                      "recognition": self._recognition_info()}
        # Variantes do vídeo, chave (áreas, caixas): (False, False) é o vídeo limpo e sempre existe; as demais
        # só são codificadas enquanto algum espectador as pede. Contadores servem a testes e diagnóstico.
        self._jpeg = {(False, False): b""}
        self.boxed_encodes = 0   # variantes com caixas já geradas
        self.areas_encodes = 0   # variantes com áreas pintadas já geradas
        self.mask_frames = 0     # quadros em que a segmentação (silhueta) foi pedida
        self.fps = 0.0

        # Telemetria em JSON, em tempo real (ver streaming/events.py)
        self.events = EventBus(cam_id, history=settings.log_history, rate=settings.log_events_per_s)
        self._last_frame_evt = 0.0
        self._prev_state = None
        self._prev_counts = None
        self._last_snapshot = 0.0
        self._conn_key = None
        self.events.emit("change", "hub.started", {"camera": cam_id})

        self._items = frozenset(settings.table_item_classes)
        self._tracker = PersonTracker()
        self._people_counter = PeopleCounter()
        self._analyzer = ZoneAnalyzer(AnalyticsConfig(
            occupy_after_s=settings.occupy_after_s, free_after_s=settings.free_after_s,
            item_hold_s=settings.item_hold_s, clean_after_s=settings.clean_after_s,
            overlap_min=settings.zone_overlap_min), zones)

        self._threads = [
            threading.Thread(target=self._reader, name=f"cam{cam_id}-read", daemon=True),
            threading.Thread(target=self._infer, name=f"cam{cam_id}-infer", daemon=True),
        ]

    def start(self):
        for t in self._threads:
            t.start()

    def stop(self):
        self.stop_event.set()
        self._wake.set()
        with self._cv:
            self._cv.notify_all()
        for t in self._threads:
            t.join(timeout=8.0)
        self._flush_flow()  # o que ainda estava em memória vai pro histórico

    @property
    def alive(self) -> bool:
        """Pipeline de pé: as duas threads rodando e ninguém pediu parada (uma thread que morreu vira zumbi)."""
        return not self.stop_event.is_set() and all(t.is_alive() for t in self._threads)

    def _reader(self):
        cap, backoff = None, 1.0
        try:
            while not self.stop_event.is_set():
                if cap is None:
                    try:
                        cap = open_source(self._get_source())
                        backoff = 1.0
                        self._set_online(True, "connected")
                        print(f"[+] câmera {self.cam_id} conectada")
                    except Exception as e:
                        self._set_online(False, "open_failed")
                        print(f"[-] câmera {self.cam_id}: {type(e).__name__} "
                              f"(nova tentativa em {backoff:.0f}s)")  # sem a fonte: tem credenciais
                        self.stop_event.wait(backoff)
                        backoff = min(backoff * 2, 15.0)
                        continue
                ok, frame = cap.read()
                if not ok or frame is None:
                    print(f"[-] câmera {self.cam_id}: perdi o frame, reconectando")
                    cap.release()
                    cap = None
                    self._set_online(False, "frame_lost")
                    continue
                with self._cv:
                    self._frame, self._fid = frame, self._fid + 1
                    self._cv.notify()
        finally:
            self.online = False
            if cap is not None:
                cap.release()

    def _set_online(self, online: bool, reason: str) -> None:
        """Atualiza `online` e anuncia só quando muda (ou muda o motivo de estar fora), sem repetir a cada tentativa."""
        self.online = online
        key = (online, reason)
        if key != self._conn_key:
            self._conn_key = key
            self.events.emit("change", "camera.online" if online else "camera.offline", {"reason": reason})

    def _has_video(self) -> bool:
        with self._pub_lock:
            return bool(self._subs) or bool(self._fsubs)

    def _has_web_video(self) -> bool:
        with self._pub_lock:
            return bool(self._subs)

    def _has_frame_subs(self) -> bool:
        with self._pub_lock:
            return bool(self._fsubs)

    def _infer(self):
        last_fid, fps = 0, 0.0
        while not self.stop_event.is_set():
            with self._cv:
                if not self._cv.wait_for(
                        lambda: self._fid != last_fid or self.stop_event.is_set(), timeout=1.0):
                    continue
                if self.stop_event.is_set():
                    break
                frame, last_fid = self._frame, self._fid
            t0 = time.monotonic()
            # ritmo: cheio com vídeo aberto; devagar (monitor_fps) quando só a análise está rodando
            has_video = self._has_video()
            target_fps = (self.fps_view or self._cfg.max_fps) if has_video else (self.fps_monitor or self._cfg.monitor_fps)
            if self.map_pin and not has_video:
                target_fps = max(target_fps, self._cfg.map_fps)   # o mapa precisa de ritmo para mostrar o movimento
            try:
                enabled, classes = self._recognition
                wants, nwants = self._wanted(), self._wanted_frames()
                # a silhueta só custa quando alguém vê as áreas, elas existem e há o que reconhecer
                need_masks = bool(self._cfg.occlusion and enabled and classes != frozenset()
                                  and any(areas for areas, _ in (wants | nwants)))
                dets = self._detector.detect(frame, classes, masks=need_masks) if enabled else []
                self.mask_frames += need_masks
                has_web = self._has_web_video()
                variants = self._encode_variants(frame, dets, wants) if has_web else {}  # sem espectador web: zero JPEG
                frames = self._render_frames(frame, dets, nwants) if self._has_frame_subs() else {}
                if not has_web:
                    with self._pub_lock:  # não deixa um quadro velho de primeira imagem pro próximo espectador
                        self._jpeg = {(False, False): b""}
                now = time.monotonic()
                state = self._build_state(dets, frame.shape, now)
                self._publish(variants, state, frames)
                self._emit_telemetry(dets, state, now)
            except Exception as e:  # um quadro ruim não derruba a câmera por horas (nem mata a thread em silêncio)
                print(f"[-] inferência câmera {self.cam_id}: {type(e).__name__}: {e}")
                self.stop_event.wait(0.5)
                continue
            dt = max(time.monotonic() - t0, 1e-4)
            fps = 0.9 * fps + 0.1 * (1.0 / dt) if fps else 1.0 / dt
            self.fps = min(fps, target_fps)
            self._wake.wait(max(0.0, 1.0 / target_fps - dt))  # teto de FPS: poupa a CPU; novo espectador interrompe
            self._wake.clear()

    def _encode_variants(self, frame, dets: list, wants: set) -> dict:
        """{(áreas, caixas): jpeg} — o limpo sempre; os demais só se algum espectador pediu."""
        params = [int(cv2.IMWRITE_JPEG_QUALITY), self._cfg.jpeg_quality]

        def enc(img):
            ok, buf = cv2.imencode(".jpg", img, params)
            return buf.tobytes() if ok else None

        out = {(False, False): enc(frame)}
        if out[(False, False)] is None:
            raise RuntimeError("falha ao codificar o JPEG")
        if any(a for a, _ in wants):
            statuses = {a["id"]: a["status"] for a in self.state.get("areas", []) if "status" in a}
            occluders = [d["poly"] for d in dets
                         if d.get("poly") and d["name"] not in self._cfg.occluder_exclude]
            rec = self._recognition
            blind = (not rec[0]) or rec[1] == frozenset() or (rec[1] is not None and 0 not in rec[1])
            painted = frame.copy()
            draw_areas(painted, self._analyzer.zones, statuses, occluders or None, blind)
            out[(True, False)] = enc(painted)
            self.areas_encodes += 1
            if (True, True) in wants:
                draw_detections(painted, dets)  # caixas por cima das áreas
                out[(True, True)] = enc(painted)
                self.boxed_encodes += 1
        if (False, True) in wants:
            marked = frame.copy()
            draw_detections(marked, dets)
            out[(False, True)] = enc(marked)
            self.boxed_encodes += 1
        return out

    def _render_frames(self, frame, dets: list, wants: set) -> dict:
        """{(áreas, caixas): quadro BGR} para os espectadores nativos: o mesmo desenho do `_encode_variants`, sem codificar."""
        out = {(False, False): frame}
        if any(a for a, _ in wants):
            statuses = {a["id"]: a["status"] for a in self.state.get("areas", []) if "status" in a}
            occluders = [d["poly"] for d in dets
                         if d.get("poly") and d["name"] not in self._cfg.occluder_exclude]
            rec = self._recognition
            blind = (not rec[0]) or rec[1] == frozenset() or (rec[1] is not None and 0 not in rec[1])
            painted = frame.copy()
            draw_areas(painted, self._analyzer.zones, statuses, occluders or None, blind)
            out[(True, False)] = painted
            if (True, True) in wants:
                boxed = painted.copy()
                draw_detections(boxed, dets)
                out[(True, True)] = boxed
        if (False, True) in wants:
            marked = frame.copy()
            draw_detections(marked, dets)
            out[(False, True)] = marked
        return out

    def _emit_telemetry(self, dets: list, state: dict, now: float) -> None:
        """Mudanças a cada quadro (já estabilizadas), resumo a 1 Hz e, só se alguém pede, o quadro detalhado."""
        for event, data in diff_states(self._prev_state, state):
            self.events.emit("change", event, data)
        self._prev_state = state
        if now - self._last_snapshot >= SNAPSHOT_EVERY_S:
            counts = counts_of(state)
            for event, data in diff_counts(self._prev_counts, counts):
                self.events.emit("change", event, data)
            self._prev_counts = counts
            self._last_snapshot = now
            self.events.emit("snapshot", "state", snapshot_of(state, self.fps, self.viewers, self.online))
        self._sample_flow(state)
        # quadro detalhado: só com ouvinte pedindo, e amostrado (a depuração não precisa de todo quadro)
        if now - self._last_frame_evt >= 1.0 / self._cfg.log_frame_hz and self.events.wants_detail():
            self._last_frame_evt = now
            self.events.emit("frame", "frame", frame_of(dets, state, self.fps))

    def _can_measure_people(self, state: dict) -> bool:
        """Só vale como medida se a câmera está no ar, o reconhecimento ligado e "Pessoa" habilitada:
        senão "0 pessoas" seria mentira (cegueira), e não ausência de gente."""
        rec = state.get("recognition") or {}
        return bool(self.online and rec.get("enabled") and rec.get("classes") != 0 and rec.get("person")
                    and state.get("people") is not None)

    def _sample_flow(self, state: dict) -> None:
        """Uma amostra por segundo da contagem já estabilizada → agregador em memória. Nada de banco aqui."""
        ts = time.time()
        if ts - self._last_flow_sample < 0.9:       # tolerância: com 1 fps os quadros chegam ~0,99 s um do outro
            return
        self._last_flow_sample = ts
        if self._can_measure_people(state):
            self._flow.sample(ts, state["people"], state.get("areas", []))
        if self._flow.due(ts):
            self._flush_flow(ts)

    def _flush_flow(self, ts: Optional[float] = None) -> None:
        batch = self._flow.flush(ts)
        if batch and self._flow_sink:
            try:
                self._flow_sink(batch)   # só enfileira; quem grava é a thread escritora
            except Exception as e:
                print(f"[-] histórico de fluxo da câmera {self.cam_id}: {type(e).__name__}")

    def _build_state(self, dets: list, shape, now: float) -> dict:
        """Inventário por classe, pessoas na área da câmera e análise das áreas do utilizador."""
        state = summarize(dets)
        state["size"] = [int(shape[1]), int(shape[0])]  # [largura, altura]: o overlay do cliente usa
        state["recognition"] = self._recognition_info()
        if not self._recognition[0]:
            # desligado: não inventa "0 pessoas" nem mesas livres — a UI mostra "reconhecimento desligado"
            state.update(people=None, areas=[])
            return state
        persons = [d["box"] for d in dets if d["name"] == "person"]
        state["people"] = self._people_counter.update(len(persons), now)
        tracked = self._tracker.update(persons, now) if (self._analyzer.has_zones or self.map_pin) else []
        # pés (centro da base da caixa) com id anônimo: só para o Mapa; nada disso vai para o disco
        state["tracks"] = [{"id": i, "x": round((b[0] + b[2]) / 2, 4), "y": round(b[3], 4), "h": round(b[3] - b[1], 4),
                            "full": b[1] > 0.01 and b[3] < 0.985}      # "full": corpo inteiro no quadro (serve para estimar a escala)
                           for i, b in tracked]
        if self._analyzer.has_zones:
            people = tracked
            items = [d["box"] for d in dets if d["name"] in self._items]
            state.update(self._analyzer.update(people, items, now, shape[1] / shape[0]))
        else:
            state["areas"] = []
        return state

    def _recognition_info(self) -> dict:
        enabled, classes = self._recognition
        # `person`: sem a classe Pessoa marcada, nenhuma mesa pode ficar ocupada (a UI avisa em vez de dizer "Livre")
        return {"enabled": enabled, "classes": None if classes is None else len(classes),
                "person": classes is None or 0 in classes}

    def set_fps(self, fps_view: Optional[float], fps_monitor: Optional[float]) -> None:
        """FPS desta câmera (None = padrão do sistema). Vale na hora: o próximo ciclo da inferência já usa."""
        self.fps_view, self.fps_monitor = fps_view, fps_monitor
        self._wake.set()

    def set_recognition(self, enabled: bool, classes: frozenset) -> None:
        """Chamado por thread de request: troca a configuração e zera o que dependia da anterior
        (contagem estabilizada, rastreador e estado das mesas) pra não herdar valores velhos."""
        new = (bool(enabled), frozenset(classes))
        if new == self._recognition:
            return
        self._recognition = new
        self.events.emit("change", "recognition.changed",
                         {"enabled": new[0], "classes": sorted(new[1]), "count": len(new[1])})
        self._people_counter = PeopleCounter()
        self._tracker = PersonTracker()
        self._analyzer.reset()

    # -- áreas (chamado por threads de request) --
    def set_zones(self, zones: Iterable[Zone]) -> None:
        self._analyzer.set_zones(zones)
        self.events.emit("change", "zones.updated", {"count": len(self._analyzer.zones)})

    def mark_clean(self, zone_id: int) -> None:
        self._analyzer.mark_clean(zone_id, time.monotonic())
        name = next((z.name for z in self._analyzer.zones if z.id == zone_id), None)
        self.events.emit("change", "area.cleaned", {"id": zone_id, "name": name})

    def _wanted(self) -> set:
        """Variantes (áreas, caixas) que algum espectador pede agora. Sem áreas desenhadas, "áreas" não
        muda o vídeo: vira a variante sem áreas (não paga codificação nem segmentação à toa)."""
        has_zones = self._analyzer.has_zones
        with self._pub_lock:
            return {(areas and has_zones, boxes) for _, _, areas, boxes in self._subs}

    def _wanted_frames(self) -> set:
        """Variantes (áreas, caixas) que os espectadores nativos pedem agora."""
        has_zones = self._analyzer.has_zones
        with self._pub_lock:
            return {(areas and has_zones, boxes) for _, areas, boxes in self._fsubs}

    def _publish(self, variants: dict, state: dict, frames: Optional[dict] = None):
        with self._pub_lock:
            self.state = state
            self._jpeg.update({k: v for k, v in variants.items() if v is not None})
            subs = list(self._subs)
            fsubs = list(self._fsubs)
        clean = variants.get((False, False))
        has_zones = self._analyzer.has_zones
        for loop, q, areas, boxes in subs:
            frame = variants.get((areas and has_zones, boxes)) or clean
            if frame is None:
                continue
            with contextlib.suppress(RuntimeError):  # loop já fechou
                loop.call_soon_threadsafe(_put_latest, q, frame)
        for callback, areas, boxes in fsubs:       # nativo: entrega o quadro desenhado + o estado, na thread da inferência
            image = (frames or {}).get((areas and has_zones, boxes))
            if image is None:
                image = (frames or {}).get((False, False))
            if image is not None:
                try:
                    callback(image, state)         # quem recebe só converte e entrega à interface (rápido, sem bloquear)
                except Exception as e:
                    print(f"[-] câmera {self.cam_id}: o ouvinte de vídeo falhou: {type(e).__name__}")
        self.ready.set()

    def last_jpeg(self, boxes: bool = False, areas: bool = False) -> bytes:
        with self._pub_lock:
            return self._jpeg.get((areas and self._analyzer.has_zones, boxes)) or self._jpeg[(False, False)]

    def subscribe(self, loop, boxes: bool = True, areas: bool = True) -> asyncio.Queue:
        q = asyncio.Queue(maxsize=1)
        with self._pub_lock:
            self._subs.append((loop, q, areas, boxes))
        self._wake.set()
        return q

    def subscribe_frames(self, callback: Callable, boxes: bool = True, areas: bool = True):
        """Espectador nativo: `callback(quadro_bgr, estado)` a cada quadro processado. Devolve o token para `unsubscribe_frames`."""
        token = (callback, areas, boxes)
        with self._pub_lock:
            self._fsubs.append(token)
        self._wake.set()
        return token

    def unsubscribe_frames(self, token) -> None:
        with self._pub_lock:
            self._fsubs = [x for x in self._fsubs if x is not token]

    def unsubscribe(self, q) -> None:
        with self._pub_lock:
            self._subs = [x for x in self._subs if x[1] is not q]

    def snapshot_state(self) -> dict:
        with self._pub_lock:
            st = dict(self.state)
        st.update(fps=round(self.fps, 1), viewers=self.viewers, online=self.online)
        return st
