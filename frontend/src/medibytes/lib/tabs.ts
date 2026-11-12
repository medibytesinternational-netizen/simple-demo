/** Element ids linking a tab to its panel (aria-controls / aria-labelledby). */
export const tabId = (prefix: string, id: string): string => `${prefix}-tab-${id}`;
export const tabPanelId = (prefix: string, id: string): string => `${prefix}-panel-${id}`;
