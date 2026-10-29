from contextvars import ContextVar

current_user_var = ContextVar('current_user', default=None)
current_branch_id_var = ContextVar('current_branch_id', default=None)
