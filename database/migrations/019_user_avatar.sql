-- 个人中心头像：原图二进制直接存列内（客户端已压缩到 256px 级别），
-- /auth/me 以 data URL 返回，图片展示无需额外鉴权头。
ALTER TABLE sys_users
    ADD COLUMN avatar MEDIUMBLOB NULL;
