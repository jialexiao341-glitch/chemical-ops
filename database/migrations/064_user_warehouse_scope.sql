CREATE TABLE sys_user_warehouse_scopes (
    user_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
    CONSTRAINT fk_user_warehouse_scope_user FOREIGN KEY (user_id) REFERENCES sys_users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE sys_user_warehouse_grants (
    user_id BIGINT UNSIGNED NOT NULL,
    warehouse_id BIGINT UNSIGNED NOT NULL,
    PRIMARY KEY (user_id, warehouse_id),
    CONSTRAINT fk_user_warehouse_grants_scope FOREIGN KEY (user_id) REFERENCES sys_user_warehouse_scopes(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_user_warehouse_grants_warehouse FOREIGN KEY (warehouse_id) REFERENCES warehouses(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
