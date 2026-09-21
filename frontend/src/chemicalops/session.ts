import type { CurrentUser } from "./types";

import { useAuthStore } from "#src/store/auth";
import { useUserStore } from "#src/store/user";

export function useChemicalOpsSession() {
	const token = useAuthStore(state => state.token);
	const userInfo = useUserStore();

	const user: CurrentUser | null = userInfo.id
		? {
				id: Number(userInfo.id),
				username: userInfo.username,
				display_name: userInfo.display_name,
				email: userInfo.email || null,
				phone: userInfo.phoneNumber || null,
				status: userInfo.status,
				role_codes: userInfo.role_codes,
				permission_codes: userInfo.permission_codes,
			}
		: null;

	return { token, user };
}
