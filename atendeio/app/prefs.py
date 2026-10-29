"""Preferências da interface (filtros da Análise, posição das janelas, limiares do mapa).

SEMPRE pelo formato INI e por esta função: `QSettings("org", "app")` usa o formato NATIVO e ignora `setDefaultFormat`, o que
impede os testes de isolar a configuração real do utilizador (setPath só redireciona o formato escolhido). Com INI explícito o
arquivo é o mesmo em qualquer sistema e o isolamento dos testes (`QSettings.setPath(IniFormat, ...)`) funciona."""

from PySide6.QtCore import QSettings


def settings() -> QSettings:
    return QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "atendeIO", "atendeIO")
