"""Catálogo das 80 classes do YOLO (COCO): id, nome do modelo, rótulo em português e grupo.

A ordem é a do modelo (o id é o índice). `Detector.load` confere com `model.names` e avisa se
um modelo treinado trouxer outra lista (aí é só trocar este catálogo)."""

_GROUPS = [
    ("Pessoas", [("person", "Pessoa")]),
    ("Mesa e cozinha", [("bottle", "Garrafa"), ("wine glass", "Taça"), ("cup", "Copo / xícara"), ("fork", "Garfo"),
                        ("knife", "Faca"), ("spoon", "Colher"), ("bowl", "Tigela")]),
    ("Comida", [("banana", "Banana"), ("apple", "Maçã"), ("sandwich", "Sanduíche"), ("orange", "Laranja"),
                ("broccoli", "Brócolis"), ("carrot", "Cenoura"), ("hot dog", "Cachorro-quente"), ("pizza", "Pizza"),
                ("donut", "Rosquinha"), ("cake", "Bolo")]),
    ("Móveis", [("chair", "Cadeira"), ("couch", "Sofá"), ("potted plant", "Planta em vaso"), ("bed", "Cama"),
                ("dining table", "Mesa de jantar"), ("toilet", "Vaso sanitário")]),
    ("Eletrônicos", [("tv", "TV"), ("laptop", "Notebook"), ("mouse", "Mouse"), ("remote", "Controle remoto"),
                     ("keyboard", "Teclado"), ("cell phone", "Celular")]),
    ("Eletrodomésticos", [("microwave", "Micro-ondas"), ("oven", "Forno"), ("toaster", "Torradeira"),
                          ("sink", "Pia"), ("refrigerator", "Geladeira")]),
    ("Objetos", [("book", "Livro"), ("clock", "Relógio"), ("vase", "Vaso"), ("scissors", "Tesoura"),
                 ("teddy bear", "Urso de pelúcia"), ("hair drier", "Secador de cabelo"), ("toothbrush", "Escova de dentes")]),
    ("Acessórios", [("backpack", "Mochila"), ("umbrella", "Guarda-chuva"), ("handbag", "Bolsa"),
                    ("tie", "Gravata"), ("suitcase", "Mala")]),
    ("Veículos", [("bicycle", "Bicicleta"), ("car", "Carro"), ("motorcycle", "Moto"), ("airplane", "Avião"),
                  ("bus", "Ônibus"), ("train", "Trem"), ("truck", "Caminhão"), ("boat", "Barco")]),
    ("Rua", [("traffic light", "Semáforo"), ("fire hydrant", "Hidrante"), ("stop sign", "Placa de pare"),
             ("parking meter", "Parquímetro"), ("bench", "Banco")]),
    ("Animais", [("bird", "Pássaro"), ("cat", "Gato"), ("dog", "Cachorro"), ("horse", "Cavalo"), ("sheep", "Ovelha"),
                 ("cow", "Vaca"), ("elephant", "Elefante"), ("bear", "Urso"), ("zebra", "Zebra"), ("giraffe", "Girafa")]),
    ("Esportes", [("frisbee", "Frisbee"), ("skis", "Esquis"), ("snowboard", "Snowboard"), ("sports ball", "Bola"),
                  ("kite", "Pipa"), ("baseball bat", "Taco de beisebol"), ("baseball glove", "Luva de beisebol"),
                  ("skateboard", "Skate"), ("surfboard", "Prancha de surfe"), ("tennis racket", "Raquete de tênis")]),
]

def catalog() -> list:
    """[{"id","name","label","group"}] ordenado por grupo (como o modal mostra)."""
    ids = {n: i for i, n in enumerate(_ordered_names())}
    out = []
    for group, items in _GROUPS:
        for name, label in items:
            out.append({"id": ids[name], "name": name, "label": label, "group": group})
    return out


def _ordered_names() -> list:
    return [
        "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light",
        "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
        "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
        "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard",
        "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
        "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
        "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard", "cell phone",
        "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
        "hair drier", "toothbrush",
    ]


NUM_CLASSES = len(_ordered_names())


def ids_for(names) -> list:
    index = {n: i for i, n in enumerate(_ordered_names())}
    return sorted(index[n] for n in names if n in index)
