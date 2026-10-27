// Tipos da API do atendeIO (espelham as respostas do servidor FastAPI).

export type CameraKind = 'local' | 'rtsp';
export interface Camera { id: number; name: string; kind: CameraKind; ref: string; }
export interface RtspPreset { label: string; path: string; }
export interface CamerasResponse { cameras: Camera[]; presets: Record<string, RtspPreset>; }
export interface LocalDevice { ref: string; name: string; mine: boolean; }

export type ZoneKind = 'mesa' | 'balcao' | 'entrada' | 'saida' | 'fila' | 'area';
export type ShapeKind = 'poly' | 'rect' | 'square' | 'ellipse' | 'triangle';
export type Point = [number, number];
export interface Zone {
  id: number | null; name: string; kind: ZoneKind; shape: ShapeKind;
  angle: number; margin: number; points: Point[];
}

export type TableStatus = 'livre' | 'ocupada' | 'a_limpar';
export interface AreaState {
  id: number; name: string; kind: ZoneKind; status?: TableStatus;
  people: number; items?: number; seconds?: number; wait?: number;
}
export interface RecognitionInfo { enabled: boolean; classes: number | null; person: boolean; }
export interface CameraState {
  total: number; counts: { name: string; count: number }[]; areas: AreaState[];
  people: number | null; size: [number, number] | null; recognition: RecognitionInfo;
  fps: number; viewers: number; online: boolean;
}

export interface RecognitionSettings { enabled: boolean; classes: number[]; }
export interface ClassInfo { id: number; name: string; label: string; group: string; }
export interface ClassPreset { id: string; label: string; description: string; classes: number[]; }
export interface ClassCatalog { classes: ClassInfo[]; presets: ClassPreset[]; }

export interface MonitorSettings { enabled: boolean; from: string; to: string; person_ready: boolean; }

export interface FlowHour { hour: number; avg: number | null; max: number | null; samples: number; }
export interface FlowDay { date: string; weekday: string; avg: number | null; max: number; samples: number; }
export interface FlowArea { zone_id: number; name: string; kind: string; avg: number | null; max: number; samples: number; }
export interface FlowRank { hour: number; avg: number; max: number; samples: number; }
export interface FlowWeekday { weekday: string; index: number; avg: number; max: number; samples: number; }
export interface FlowReport {
  summary: {
    avg: number | null; samples: number; coverage: number; days_with_data: number;
    peak: { value: number; at: string; hour: number; weekday: string } | null;
    busiest_hours: FlowRank[]; emptiest_hours: FlowRank[];
    busiest_weekday: FlowWeekday | null; emptiest_weekday: FlowWeekday | null;
  };
  hourly: FlowHour[]; daily: FlowDay[]; weekday: FlowWeekday[];
  heatmap: (number | null)[][]; areas: FlowArea[]; insights: string[];
  range: { from: string; to: string; hour_from: number; hour_to: number; timezone: string };
}
export interface DayPoint { t: string; avg: number | null; max: number; samples: number; }
export interface FlowDaySeries { date: string; timezone: string; series: DayPoint[]; }
