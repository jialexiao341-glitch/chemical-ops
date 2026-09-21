import type { FormValues, TableActionProps } from '@vben/common-ui';
import type { VxeTableGridOptions } from '@vben/plugins/vxe-table';
import type { Recordable } from '@vben/types';

import type { ComponentPropsMap, ComponentType } from './component';

import { defineComponent, h } from 'vue';

import { useAccess } from '@vben/access';
import { VbenTableAction as VbenTableActionCore } from '@vben/common-ui';
import { IconifyIcon } from '@vben/icons';
import { $te } from '@vben/locales';
import {
  setupVbenVxeTable,
  useVbenVxeGrid as useGrid,
} from '@vben/plugins/vxe-table';
import { get, isFunction, isString } from '@vben/utils';

import { objectOmit } from '@vueuse/core';
import { Button, Dropdown, Image, Popconfirm, Switch, Tag } from 'antdv-next';

import { $t } from '#/locales';

import { useVbenForm } from './form';

setupVbenVxeTable({
  configVxeTable: (vxeUI) => {
    vxeUI.setConfig({
      grid: {
        align: 'center',
        border: false,
        columnConfig: {
          resizable: true,
        },
        formConfig: {
          // 全局禁用vxe-table自带的表单配置，统一使用 formOptions
          enabled: false,
        },
        minHeight: 180,
        proxyConfig: {
          autoLoad: true,
          // ChemicalOps 后端分页结构为 { items, total, page, page_size }
          response: {
            list: 'items',
            result: 'items',
            total: 'total',
          },
          showActiveMsg: true,
          showResponseMsg: false,
        },
        round: true,
        showOverflow: true,
        size: 'small',
      } as VxeTableGridOptions,
    });

    /**
     * 解决 vxe-table 在热更新时可能出错的问题
     */
    vxeUI.renderer.forEach((_item, key) => {
      if (key.startsWith('Cell')) {
        vxeUI.renderer.delete(key);
      }
    });

    // 用法：cellRender: { name: 'CellImage' }
    vxeUI.renderer.add('CellImage', {
      renderTableDefault(renderOpts, params) {
        const { props } = renderOpts;
        const { column, row } = params;
        return h(Image, { src: row[column.field], ...props });
      },
    });

    // 用法：cellRender: { name: 'CellLink' }
    vxeUI.renderer.add('CellLink', {
      renderTableDefault(renderOpts) {
        const { props } = renderOpts;
        return h(
          Button,
          { size: 'small', type: 'link' },
          { default: () => props?.text },
        );
      },
    });

    /**
     * 单元格渲染：状态标签
     *
     * 通过 `options` 传入字典项，例如：
     * cellRender: { name: 'CellTag', options: ORDER_STATUS_DICT.items }
     */
    vxeUI.renderer.add('CellTag', {
      renderTableDefault({ options, props }, { column, row }) {
        const value = get(row, column.field);
        const tagOptions = options ?? [];
        const tagItem = tagOptions.find(
          (item: Recordable<any>) => item.value === value,
        );
        return h(
          Tag,
          {
            ...props,
            ...objectOmit(tagItem ?? {}, ['label']),
          },
          { default: () => tagItem?.label ?? value },
        );
      },
    });

    /**
     * 单元格渲染：状态开关，变更前会调用 `attrs.beforeChange`，
     * 返回 false 则中止切换。
     */
    vxeUI.renderer.add('CellSwitch', {
      renderTableDefault({ attrs, props }, { column, row }) {
        const loadingKey = `__loading_${column.field}`;
        const finallyProps = {
          checkedChildren: $t('common.enabled'),
          checkedValue: 'ACTIVE',
          unCheckedChildren: $t('common.disabled'),
          unCheckedValue: 'INACTIVE',
          ...props,
          checked: row[column.field],
          loading: row[loadingKey] ?? false,
          'onUpdate:checked': onChange,
        };
        async function onChange(newVal: any) {
          row[loadingKey] = true;
          try {
            const result = await attrs?.beforeChange?.(newVal, row);
            if (result !== false) {
              row[column.field] = newVal;
            }
          } finally {
            row[loadingKey] = false;
          }
        }
        return h(Switch, finallyProps);
      },
    });

    /**
     * 注册表格操作按钮渲染器
     */
    vxeUI.renderer.add('CellOperation', {
      renderTableDefault({ attrs, options, props: rawProps }, { column, row }) {
        const {
          dropdownProps,
          menuButtonProps,
          menuButtonPosition = 'right',
          menuCodes = [],
          menuIcon = 'ant-design:more-outlined',
          menuText = $t('common.more'),
          mode,
          renderMode,
          ...props
        } = rawProps ?? {};
        const defaultProps = { size: 'small', type: 'link', ...props };
        let align: string;
        switch (column.align) {
          case 'center': {
            align = 'center';
            break;
          }
          case 'left': {
            align = 'start';
            break;
          }
          default: {
            align = 'end';
            break;
          }
        }
        const presets: Recordable<Recordable<any>> = {
          delete: {
            danger: true,
            text: $t('common.delete'),
          },
          edit: {
            text: $t('common.edit'),
          },
          detail: {
            text: $t('common.detail'),
          },
        };
        const operations: Array<Recordable<any>> = (
          options || ['edit', 'detail', 'delete']
        )
          .map((opt) => {
            if (isString(opt)) {
              return presets[opt]
                ? { code: opt, ...presets[opt], ...defaultProps }
                : {
                    code: opt,
                    text: $te(`common.${opt}`) ? $t(`common.${opt}`) : opt,
                    ...defaultProps,
                  };
            } else {
              return { ...defaultProps, ...presets[opt.code], ...opt };
            }
          })
          .map((opt) => {
            const optBtn: Recordable<any> = {};
            Object.keys(opt).forEach((key) => {
              optBtn[key] = isFunction(opt[key]) ? opt[key](row) : opt[key];
            });
            return optBtn;
          })
          .filter((opt) => opt.show !== false);

        function renderBtn(opt: Recordable<any>, listen = true) {
          return h(
            Button,
            {
              ...props,
              ...opt,
              icon: undefined,
              onClick: listen
                ? () =>
                    attrs?.onClick?.({
                      code: opt.code,
                      row,
                    })
                : undefined,
            },
            {
              default: () => {
                const content = [];
                if (opt.icon) {
                  content.push(
                    h(IconifyIcon, { class: 'size-5', icon: opt.icon }),
                  );
                }
                content.push(opt.text);
                return content;
              },
            },
          );
        }

        function renderConfirm(opt: Recordable<any>) {
          let viewportWrapper: HTMLElement | null = null;
          return h(
            Popconfirm,
            {
              /**
               * 固定列中的 Popconfirm 容器选择较麻烦：以 body 作为容器时
               * 弹窗无法跟随表格滚动。折中方案是弹窗打开时禁止表格滚动。
               */
              getPopupContainer(el) {
                viewportWrapper = el.closest('.vxe-table--viewport-wrapper');
                return document.body;
              },
              placement: 'topLeft',
              title: $t('ui.actionTitle.delete', [attrs?.nameTitle || '']),
              ...props,
              ...opt,
              icon: undefined,
              onOpenChange: (open: boolean) => {
                if (open) {
                  viewportWrapper?.style.setProperty('pointer-events', 'none');
                } else {
                  viewportWrapper?.style.removeProperty('pointer-events');
                }
              },
              onConfirm: () => {
                attrs?.onClick?.({
                  code: opt.code,
                  row,
                });
              },
            },
            {
              default: () => renderBtn({ ...opt }, false),
              description: () =>
                h(
                  'div',
                  { class: 'truncate' },
                  $t('ui.actionMessage.deleteConfirm', [
                    row[attrs?.nameField || 'name'],
                  ]),
                ),
            },
          );
        }

        const renderOperation = (opt: Recordable<any>) =>
          opt.code === 'delete' ? renderConfirm(opt) : renderBtn(opt);
        const btns = operations.map((operation) => renderOperation(operation));

        function renderMenuTrigger() {
          return h(
            Button,
            {
              size: defaultProps.size,
              type: defaultProps.type,
              ...menuButtonProps,
            },
            {
              default: () => {
                const content = [];
                if (menuIcon) {
                  content.push(
                    h(IconifyIcon, { class: 'size-5', icon: menuIcon }),
                  );
                }
                if (menuText) {
                  content.push(h('span', menuText));
                }
                return h(
                  'div',
                  { class: 'inline-flex items-center gap-1 leading-none' },
                  content,
                );
              },
            },
          );
        }

        const operationRenderStrategies = {
          button: () => btns,
          menu: () => {
            const hasMenuCodes =
              Array.isArray(menuCodes) && menuCodes.length > 0;
            const menuCodeSet = new Set(menuCodes);
            const inlineBtns = hasMenuCodes
              ? operations
                  .filter((opt) => !menuCodeSet.has(opt.code))
                  .map((operation) => renderOperation(operation))
              : [];
            const menuBtns = hasMenuCodes
              ? operations
                  .filter((opt) => menuCodeSet.has(opt.code))
                  .map((operation) => renderOperation(operation))
              : btns;
            const dropdownBtn =
              menuBtns.length > 0
                ? [
                    h(
                      Dropdown,
                      {
                        getPopupContainer: () => document.body,
                        placement:
                          column.align === 'left'
                            ? 'bottomLeft'
                            : 'bottomRight',
                        trigger: ['click'],
                        ...dropdownProps,
                      },
                      {
                        default: () =>
                          h(
                            'span',
                            {
                              class: 'inline-flex cursor-pointer',
                            },
                            [renderMenuTrigger()],
                          ),

                        popupRender: () =>
                          h(
                            'div',
                            {
                              class:
                                'ant-dropdown-menu flex flex-col gap-1 p-1',

                              onClick: (event: MouseEvent) =>
                                event.stopPropagation(),

                              style: {
                                minWidth: '80px',
                              },
                            },
                            menuBtns,
                          ),
                      },
                    ),
                  ]
                : [];

            return hasMenuCodes && menuButtonPosition === 'left'
              ? [...dropdownBtn, ...inlineBtns]
              : [...inlineBtns, ...dropdownBtn];
          },
        };
        const renderOperations =
          (renderMode ?? mode) === 'menu'
            ? operationRenderStrategies.menu
            : operationRenderStrategies.button;

        return h(
          'div',
          {
            class: 'flex table-operations',
            style: { justifyContent: align },
          },
          renderOperations(),
        );
      },
    });
  },
  useVbenForm,
});

export const useVbenVxeGrid = <
  T extends Record<string, any>,
  TFormValues extends FormValues = FormValues,
  TSubmitValues extends FormValues = TFormValues,
>(
  ...rest: Parameters<
    typeof useGrid<
      T,
      ComponentType,
      ComponentPropsMap,
      TFormValues,
      TSubmitValues
    >
  >
) =>
  useGrid<T, ComponentType, ComponentPropsMap, TFormValues, TSubmitValues>(
    ...rest,
  );

/**
 * 表格操作按钮组件
 *
 * 在适配器内部统一注入权限判断（hasPermission），
 * 通过 action 的 `auth` 字段声明权限码。
 */
export const VbenTableAction = defineComponent(
  (props: TableActionProps, { attrs, slots }) => {
    const { hasAccessByCodes } = useAccess();
    function hasPermission(auth?: string | string[]) {
      if (!auth) return true;
      return hasAccessByCodes(Array.isArray(auth) ? auth : [auth]);
    }
    return () =>
      h(VbenTableActionCore, { hasPermission, ...props, ...attrs }, slots);
  },
  {
    name: 'VbenTableAction',
    inheritAttrs: false,
  },
);

export type OnActionClickParams<T = Recordable<any>> = {
  code: string;
  row: T;
};
export type OnActionClickFn<T = Recordable<any>> = (
  params: OnActionClickParams<T>,
) => void;
export type * from '@vben/plugins/vxe-table';
