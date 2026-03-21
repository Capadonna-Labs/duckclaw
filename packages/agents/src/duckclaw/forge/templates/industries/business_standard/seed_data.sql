-- Catálogos maestros: perfil sistema, roles RBAC (spec v3.0)

INSERT INTO core.profiles (id, document_number, full_name, email, bio, created_by, updated_by)
VALUES (
    'profile_system',
    'SYSTEM',
    'System Bootstrap',
    'system@local.invalid',
    'Cuenta interna para auditoría y FKs iniciales',
    NULL,
    NULL
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO rbac.roles (id, name, created_by, updated_by)
VALUES
    ('role_admin', 'admin', 'profile_system', 'profile_system'),
    ('role_manager', 'manager', 'profile_system', 'profile_system'),
    ('role_viewer', 'viewer', 'profile_system', 'profile_system')
ON CONFLICT (id) DO NOTHING;

INSERT INTO rbac.permissions (id, name, created_by, updated_by)
VALUES
    ('perm_all', '*', 'profile_system', 'profile_system'),
    ('perm_read', 'read', 'profile_system', 'profile_system'),
    ('perm_write', 'write', 'profile_system', 'profile_system')
ON CONFLICT (id) DO NOTHING;
