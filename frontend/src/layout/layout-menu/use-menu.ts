import type { MenuProps } from "antd";

import { useCurrentRoute } from "#src/hooks/use-current-route";
import { removeTrailingSlash } from "#src/router/utils/remove-trailing-slash";
import { useAccessStore } from "#src/store/access";

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useMatches, useNavigate } from "react-router";

import { useLayout } from "../hooks";
import type { MenuItemType } from "./types";
import { findDeepestFirstItem, findRootMenuByPath, translateMenus } from "./utils";

const chemicalOpsGroupDefinitions: Array<{ key: string, label: string, routes: string[] }> = [
	{
		key: "/chemicalops/group/products",
		label: "化工产品",
		routes: [
			"/chemicalops/procurement",
			"/chemicalops/deliveries",
			"/chemicalops/inbounds",
		],
	},
	{
		key: "/chemicalops/group/inventory",
		label: "库存管理",
		routes: ["/chemicalops/inventory-quality", "/chemicalops/quality", "/chemicalops/warehouse"],
	},
	{
		key: "/chemicalops/group/suppliers",
		label: "供应商",
		routes: ["/chemicalops/sourcing", "/chemicalops/supplier-portal"],
	},
	{
		key: "/chemicalops/group/operations",
		label: "运营管理",
		routes: ["/chemicalops/finance", "/chemicalops/control", "/chemicalops/files"],
	},
	{
		key: "/chemicalops/group/analysis",
		label: "智能分析",
		routes: ["/chemicalops/ai"],
	},
	{
		key: "/chemicalops/group/system",
		label: "组织与权限",
		routes: ["/chemicalops/system"],
	},
];

function groupChemicalOpsMenus(menus: MenuItemType[]) {
	return menus.flatMap((menu) => {
		if (menu.key !== "/chemicalops" || !menu.children?.length) {
			return [menu];
		}

		const menuByKey = new Map(menu.children.map(item => [item.key, item]));
		const groupedKeys = new Set<string>();
		const groups = chemicalOpsGroupDefinitions.flatMap((definition) => {
			const children = definition.routes.flatMap((route) => {
				const item = menuByKey.get(route);
				if (item) {
					groupedKeys.add(route);
				}
				return item ? [item] : [];
			});

			return children.length
				? [{ key: definition.key, label: definition.label, children }]
				: [];
		});

		const ungrouped = menu.children.filter(item => !groupedKeys.has(item.key));
		return [...groups, ...ungrouped];
	});
}

export function useMenu() {
	const wholeMenus = useAccessStore(state => state.wholeMenus);
	const { isMixedNav, isTwoColumnNav } = useLayout();
	const navigate = useNavigate();
	const { t } = useTranslation();
	const translatedMenus = useMemo(
		() => groupChemicalOpsMenus(translateMenus(wholeMenus, t)),
		[wholeMenus, t],
	);

	const { pathname } = useCurrentRoute();
	const matches = useMatches();
	/**
	 * 混合菜单模式下需要拆分 menu 的 items
	 */
	const shouldSplitMenuItems = useMemo(
		() => isMixedNav || isTwoColumnNav,
		[isMixedNav, isTwoColumnNav],
	);

	/**
	 * 混合导航模式下，侧边导航的顶级菜单 key
	 */
	const sideNavMenuKeyInSplitMode = useMemo(() => {
		if (!shouldSplitMenuItems)
			return "";

		// Try to find active menu from currentActiveMenu first
		const activeMenuPath = matches.findLast(routeItem =>
			routeItem.handle?.currentActiveMenu,
		)?.handle?.currentActiveMenu;

		// Fallback to current pathname if no currentActiveMenu found
		const targetPath = activeMenuPath ? removeTrailingSlash(activeMenuPath) : removeTrailingSlash(pathname);

		const { rootMenuPath } = findRootMenuByPath(translatedMenus, targetPath);
		return rootMenuPath ?? "";
	}, [shouldSplitMenuItems, pathname, matches]);

	/* 混合菜单模式下需要拆分 menu 的 items */
	const splitSideNavItems = useMemo(
		() => {
			const foundMenu = translatedMenus.find(item => item?.key === sideNavMenuKeyInSplitMode);
			if (!foundMenu) {
				return [];
			}
			return foundMenu?.children ?? [foundMenu];
		},
		[sideNavMenuKeyInSplitMode, translatedMenus],
	);

	/**
	 * 头部菜单
	 */
	const topNavItems = useMemo(() => {
		if (!shouldSplitMenuItems) {
			return translatedMenus;
		}
		return translatedMenus.map((item) => {
			return {
				...item,
				/* children 为空数组，无法触发 menu 的 onSelect 事件 */
				children: undefined,
			};
		});
	}, [shouldSplitMenuItems, translatedMenus]);

	/**
	 * 侧边菜单
	 */
	const sideNavItems = useMemo(() => {
		return shouldSplitMenuItems ? splitSideNavItems : translatedMenus;
	}, [shouldSplitMenuItems, splitSideNavItems, translatedMenus]);

	/**
	 * 菜单点击事件处理
	 */
	const handleMenuSelect = (key: string, mode: MenuProps["mode"]) => {
		if (key.startsWith("/chemicalops/group/")) {
			return;
		}
		if (key === removeTrailingSlash(pathname)) {
			return;
		}
		/* 1. 非混合导航模式 2. 混合导航模式下的侧边导航 */
		if (!shouldSplitMenuItems || mode !== "horizontal") {
			// eslint-disable-next-line regexp/no-unused-capturing-group
			if (/http(s)?:/.test(key)) {
				window.open(key);
			}
			else {
				navigate(key);
			}
		}
		else {
			/* 混合导航模式下的顶部导航 */
			const rootMenu = translatedMenus.find(item => item?.key === key);
			const targetMenu = findDeepestFirstItem(rootMenu?.children ?? []);
			/* 点击顶部的导航默认跳转到菜单下的第一个子项 */
			if (!targetMenu) {
				navigate(key);
			}
			else {
				navigate(targetMenu.key);
			}
		}
	};

	return {
		handleMenuSelect,
		sideNavMenuKeyInSplitMode,
		topNavItems,
		sideNavItems,
	};
}
