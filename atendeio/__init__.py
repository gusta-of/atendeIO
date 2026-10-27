"""atendeIO — painel multiutilizador de câmeras com reconhecimento de ambiente (YOLO).

Camadas (a dependência só aponta pra baixo):

    api/            HTTP: rotas, schemas, middleware, deps (traduz erros de domínio em status)
    services/       regras de negócio (auth, câmeras, RTSP) — não conhece HTTP nem SQL
    repositories/   acesso a dados (SQL) — não conhece regra de negócio
    db.py           conexão e esquema SQLite
    vision/         YOLO, desenho do inventário, abertura de fontes (OpenCV)
    streaming/      pipeline por câmera (CameraHub), registro e MJPEG
    container.py    composition root: monta tudo uma vez, sem estado global em módulo
    config.py       Settings imutável, vinda de variáveis de ambiente
"""
