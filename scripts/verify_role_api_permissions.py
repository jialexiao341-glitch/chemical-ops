"""核对演示角色权限快照，并对未授权接口执行拒绝访问探测。

只向 /auth/me 确认缺少权限码的接口发请求；已授权写接口不执行。
密码由 ROLE_ACCEPTANCE_PASSWORD 环境变量提供，不写入报告。
"""
import argparse
import inspect
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
import re
import sys

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT))
from app.main import app
from scripts.seed_demo_accounts import ROLE_SCOPES, USERS


def effective_routes(routes):
    for route in routes:
        if hasattr(route, 'effective_candidates'):
            yield from effective_routes(route.effective_candidates())
        else:
            yield route, route


def protected_routes():
    for route, effective in effective_routes(app.routes):
        dependant = getattr(route, 'dependant', None)
        if dependant is None:
            continue
        for dependency in dependant.dependencies:
            function = dependency.call
            if not callable(function):
                continue
            code = inspect.getclosurevars(function).nonlocals.get('permission_code')
            if code:
                yield effective.path, route.methods, code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-url', default='http://127.0.0.1:8888')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--role', choices=sorted(role for role in ROLE_SCOPES if role != 'SYS_ADMIN'),
                        help='只验收一个非管理员角色')
    args = parser.parse_args()
    password = os.environ.get('ROLE_ACCEPTANCE_PASSWORD')
    if not password:
        parser.error('请设置 ROLE_ACCEPTANCE_PASSWORD 环境变量')
    results = []
    routes = list(protected_routes())
    if len(routes) < 100:
        raise RuntimeError('权限路由枚举不完整，拒绝生成通过结论')
    with httpx.Client(base_url=args.api_url, timeout=30) as client:
        for username, _, _, role in USERS:
            if role == 'SYS_ADMIN':
                continue
            if args.role and role != args.role:
                continue
            login = client.post('/api/v1/auth/login', json={'username': username, 'password': password})
            login.raise_for_status()
            headers = {'Authorization': 'Bearer ' + login.json()['access_token']}
            me = client.get('/api/v1/auth/me', headers=headers)
            me.raise_for_status()
            granted = set(me.json()['permission_codes'])
            expected = set(ROLE_SCOPES[role])
            probes = []
            for route_path, methods, code in routes:
                if code in granted:
                    continue
                path = re.sub(r'\{[^}]+\}', '2147483647', route_path)
                for method in sorted(methods - {'HEAD', 'OPTIONS'}):
                    response = client.request(method, path, headers=headers, json={})
                    probes.append({'method': method, 'path': route_path, 'permission': code,
                                   'status': response.status_code, 'passed': response.status_code == 403})
            result = {'role': role, 'username': username, 'permission_codes': sorted(granted),
                      'missing_expected_permissions': sorted(expected - granted),
                      'unexpected_permissions': sorted(granted - expected), 'denied_probes': probes}
            result['passed'] = not (expected - granted or granted - expected) and all(x['passed'] for x in probes)
            results.append(result)
            print(f"{role}: {len(probes)} 拒绝探测，{'通过' if result['passed'] else '失败'}", flush=True)
    role_scope = f'{args.role} 演示账号' if args.role else '11 类非管理员演示账号'
    report = {'date': datetime.now(timezone(timedelta(hours=8))).isoformat(),
              'scope': role_scope + '；真实 HTTP、权限快照及缺少权限码的接口；不代替浏览器按钮或数据归属验收',
              'roles': results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if all(x['passed'] for x in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
