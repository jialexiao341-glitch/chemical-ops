import type { ViewKey } from "../types";

import { useNavigate } from "react-router";

import { useChemicalOpsSession } from "../session";
import { LiveReferenceDashboard } from "./LiveReferencePages";

const viewPaths: Partial<Record<ViewKey, string>> = {
	ai: "/chemicalops/ai",
	purchases: "/chemicalops/procurement",
	deliveries: "/chemicalops/deliveries",
	inbounds: "/chemicalops/inbounds",
	inventory: "/chemicalops/inventory-quality",
	quality: "/chemicalops/quality",
	suppliers: "/chemicalops/procurement",
	finance: "/chemicalops/finance",
	logistics: "/chemicalops/sourcing",
	"inventory-ops": "/chemicalops/warehouse",
	exceptions: "/chemicalops/control",
	files: "/chemicalops/files",
	"supplier-portal": "/chemicalops/supplier-portal",
	system: "/chemicalops/system",
};

export default function ChemicalOpsDashboard() {
	const navigate = useNavigate();
	const { token, user } = useChemicalOpsSession();

	if (!token || !user) return null;

	return (
		<LiveReferenceDashboard
			token={token}
			user={user}
			onSelect={view => navigate(viewPaths[view] || "/home")}
		/>
	);
}
