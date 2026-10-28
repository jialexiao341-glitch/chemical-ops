CREATE TABLE sys_user_department_scopes (
    user_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
    CONSTRAINT fk_user_department_scope_user FOREIGN KEY (user_id) REFERENCES sys_users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE sys_user_department_grants (
    user_id BIGINT UNSIGNED NOT NULL,
    department_id BIGINT UNSIGNED NOT NULL,
    PRIMARY KEY (user_id, department_id),
    CONSTRAINT fk_user_department_grants_scope FOREIGN KEY (user_id) REFERENCES sys_user_department_scopes(user_id) ON DELETE CASCADE,
    CONSTRAINT fk_user_department_grants_department FOREIGN KEY (department_id) REFERENCES sys_departments(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
