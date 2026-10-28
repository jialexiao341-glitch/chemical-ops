CREATE TEMPORARY TABLE migration_warehouse_scope_users (
    user_id BIGINT UNSIGNED NOT NULL PRIMARY KEY
) ENGINE=InnoDB;

INSERT INTO migration_warehouse_scope_users (user_id)
SELECT u.id FROM sys_users u
WHERE NOT EXISTS (SELECT 1 FROM sys_user_warehouse_scopes s WHERE s.user_id = u.id)
  AND NOT EXISTS (
      SELECT 1 FROM sys_user_roles ur JOIN sys_roles r ON r.id = ur.role_id
      WHERE ur.user_id = u.id AND r.role_code IN ('SYS_ADMIN', 'SUPPLIER_PORTAL')
  );

INSERT INTO sys_user_warehouse_scopes (user_id)
SELECT user_id FROM migration_warehouse_scope_users;

INSERT INTO sys_user_warehouse_grants (user_id, warehouse_id)
SELECT m.user_id, w.id FROM migration_warehouse_scope_users m
JOIN warehouses w ON w.manager_id = m.user_id AND w.status = 'ACTIVE';

UPDATE sys_users u JOIN migration_warehouse_scope_users m ON m.user_id = u.id
SET u.token_version = u.token_version + 1;

DROP TEMPORARY TABLE migration_warehouse_scope_users;
