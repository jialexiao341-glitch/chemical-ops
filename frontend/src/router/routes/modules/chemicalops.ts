import type { AppRouteRecordRaw } from "#src/router/types";

import ContainerLayout from "#src/layout/container-layout";

import {
	BarChartOutlined,
	BankOutlined,
	CarOutlined,
	CloudUploadOutlined,
	DashboardOutlined,
	DatabaseOutlined,
	FileSearchOutlined,
	SafetyCertificateOutlined,
	SettingOutlined,
	ShoppingCartOutlined,
	TeamOutlined,
	ToolOutlined,
} from "@ant-design/icons";
import { createElement, lazy } from "react";

const dashboard = lazy(() => import("#src/chemicalops/pages/ChemicalOpsDashboard"));
const procurement = lazy(() => import("#src/chemicalops/pages/ChemicalOpsRoutePages").then(module => ({ default: module.ProcurementPage })));
const inventoryQuality = lazy(() => import("#src/chemicalops/pages/ChemicalOpsRoutePages").then(module => ({ default: module.InventoryQualityPage })));
const quality = lazy(() => import("#src/chemicalops/pages/ChemicalOpsRoutePages").then(module => ({ default: module.QualityPage })));
const ai = lazy(() => import("#src/chemicalops/pages/ChemicalOpsRoutePages").then(module => ({ default: module.AIWorkspacePage })));
const deliveries = lazy(() => import("#src/chemicalops/pages/ChemicalOpsRoutePages").then(module => ({ default: module.DeliveriesRoutePage })));
const inbounds = lazy(() => import("#src/chemicalops/pages/ChemicalOpsRoutePages").then(module => ({ default: module.InboundsRoutePage })));
const modulePage = lazy(() => import("#src/chemicalops/pages/ChemicalOpsModulePage"));

const chemicalOpsRoutes: AppRouteRecordRaw[] = [
	{
		path: "/home",
		Component: ContainerLayout,
		handle: { title: "运营总览", icon: createElement(DashboardOutlined), order: 1 },
		children: [{ index: true, Component: dashboard, handle: { title: "运营总览", icon: createElement(DashboardOutlined) } }],
	},
	{
		path: "/chemicalops",
		Component: ContainerLayout,
		handle: { title: "化工运营", icon: createElement(BarChartOutlined), order: 2, hideInBreadcrumb: true },
		children: [
			{ path: "/chemicalops/procurement", Component: procurement, handle: { title: "采购履约", icon: createElement(ShoppingCartOutlined) } },
			{ path: "/chemicalops/inventory-quality", Component: inventoryQuality, handle: { title: "库存与质量", icon: createElement(DatabaseOutlined) } },
			{ path: "/chemicalops/quality", Component: quality, handle: { title: "质量验收", icon: createElement(SafetyCertificateOutlined) } },
			{ path: "/chemicalops/ai", Component: ai, handle: { title: "AI 分析工作区", icon: createElement(CloudUploadOutlined) } },
			{ path: "/chemicalops/deliveries", Component: deliveries, handle: { title: "到货与收货", icon: createElement(CarOutlined) } },
			{ path: "/chemicalops/inbounds", Component: inbounds, handle: { title: "库存入库", icon: createElement(ToolOutlined) } },
			{ path: "/chemicalops/finance", Component: modulePage, handle: { title: "财务管理", icon: createElement(BankOutlined) } },
			{ path: "/chemicalops/sourcing", Component: modulePage, handle: { title: "询价与供应", icon: createElement(TeamOutlined) } },
			{ path: "/chemicalops/warehouse", Component: modulePage, handle: { title: "仓储作业", icon: createElement(DatabaseOutlined) } },
			{ path: "/chemicalops/control", Component: modulePage, handle: { title: "异常与通知", icon: createElement(FileSearchOutlined) } },
			{ path: "/chemicalops/files", Component: modulePage, handle: { title: "文件与附件", icon: createElement(FileSearchOutlined) } },
			{
				path: "/chemicalops/supplier-portal",
				Component: modulePage,
				handle: { title: "供应商门户", icon: createElement(TeamOutlined), roles: ["SUPPLIER_PORTAL"] },
			},
			{ path: "/chemicalops/system", Component: modulePage, handle: { title: "组织与权限", icon: createElement(SettingOutlined) } },
		],
	},
];

export default chemicalOpsRoutes;
