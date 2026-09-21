import type { AppRouteRecordRaw } from "#src/router/types";
import type { AuthType, LoginInfo, UserInfoType } from "./types";

import { request } from "#src/utils/request";
import { REFRESH_TOKEN_PATH } from "#src/utils/request/constants";

export * from "./types";

export function fetchLogin(data: LoginInfo) {
	return request
		.post("auth/login", { json: data })
		.json<{ access_token: string }>()
		.then(response => ({
			result: {
				token: response.access_token,
				refreshToken: "",
			},
		}));
}

export function fetchLogout() {
	return Promise.resolve();
}

export function fetchAsyncRoutes() {
	return request.get("get-async-routes").json<ApiResponse<AppRouteRecordRaw[]>>();
}

export function fetchUserInfo() {
	return request
		.get("auth/me")
		.json<{
			id: number
			username: string
			display_name: string
			email?: string | null
			phone?: string | null
			status: string
			role_codes: string[]
			permission_codes: string[]
		}>()
		.then(user => ({
			result: {
				id: String(user.id),
				avatar: "",
				username: user.username,
				email: user.email || "",
				phoneNumber: user.phone || "",
				display_name: user.display_name,
				status: user.status,
				role_codes: user.role_codes,
				permission_codes: user.permission_codes,
				description: "",
				roles: user.role_codes,
			},
		}));
}

export interface RefreshTokenResult {
	token: string
	refreshToken: string
}

export function fetchRefreshToken(data: { readonly refreshToken: string }) {
	return request.post(REFRESH_TOKEN_PATH, { json: data }).json<ApiResponse<RefreshTokenResult>>();
}
