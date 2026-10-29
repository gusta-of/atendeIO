"""Erros de domínio. Os services levantam estes; a camada api os traduz em HTTP."""


class DomainError(Exception):
    """Base: a mensagem é segura de mostrar ao utilizador."""


class ValidationError(DomainError):
    """Dado inválido (400)."""


class AuthError(DomainError):
    """Sem sessão ou credenciais erradas (401)."""


class ForbiddenError(DomainError):
    """Ação desativada ou proibida (403)."""


class NotFoundError(DomainError):
    """Recurso inexistente — ou de outro utilizador, de propósito indistinguível (404)."""


class ConflictError(DomainError):
    """Já existe / já em uso (409)."""


class RateLimitError(DomainError):
    """Muitas tentativas ou limite de recursos atingido (429)."""


class CredentialsRequired(DomainError):
    """Câmera RTSP sem usuário/senha nesta execução: o cliente precisa digitá-los (423). `code` é estável para a UI."""
    code = "credentials_required"
