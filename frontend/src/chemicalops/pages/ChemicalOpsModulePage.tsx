import { useLocation } from "react-router";

import { useChemicalOpsSession } from "../session";
import BusinessModulesPage from "./BusinessModulesPage";

type ModuleSection = "finance" | "logistics" | "inventory-ops" | "exceptions" | "files" | "supplier-portal" | "system";

const sectionAliases: Record<string, ModuleSection> = {
	finance: "finance",
	sourcing: "logistics",
	warehouse: "inventory-ops",
	control: "exceptions",
	files: "files",
	"supplier-portal": "supplier-portal",
	system: "system",
};

export default function ChemicalOpsModulePage() {
	const { pathname } = useLocation();
	const section = pathname.split("/").filter(Boolean).at(-1);
	const { token } = useChemicalOpsSession();

	const resolvedSection = section ? sectionAliases[section] : undefined;
	if (!token || !resolvedSection) return null;

	return <BusinessModulesPage token={token} section={resolvedSection} />;
}
