import { useChemicalOpsSession } from "../session";
import { DeliveriesPage, InboundsPage } from "./FulfillmentPages";
import {
	LiveReferenceAIWorkspace,
	LiveReferenceInventoryQuality,
	LiveReferenceProcurement,
	LiveReferenceQuality,
} from "./LiveReferencePages";

export function ProcurementPage() {
	const { token } = useChemicalOpsSession();
	return token ? <LiveReferenceProcurement token={token} /> : null;
}

export function InventoryQualityPage() {
	const { token, user } = useChemicalOpsSession();
	return token && user ? <LiveReferenceInventoryQuality token={token} user={user} /> : null;
}

export function QualityPage() {
	const { token, user } = useChemicalOpsSession();
	return token && user ? <LiveReferenceQuality token={token} user={user} /> : null;
}

export function AIWorkspacePage() {
	const { token } = useChemicalOpsSession();
	return token ? <LiveReferenceAIWorkspace token={token} /> : null;
}

export function DeliveriesRoutePage() {
	const { token } = useChemicalOpsSession();
	return token ? <DeliveriesPage token={token} /> : null;
}

export function InboundsRoutePage() {
	const { token } = useChemicalOpsSession();
	return token ? <InboundsPage token={token} /> : null;
}
