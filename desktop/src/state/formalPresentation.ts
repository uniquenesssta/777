const compiledFormal = import.meta.env?.VITE_QUOTE777_DELIVERY === 'manager' || import.meta.env?.VITE_QUOTE777_DELIVERY === 'sales';
let formal = compiledFormal;
export function setDeliveryContext(delivery:string) { formal = compiledFormal || ['manager','sales'].includes(delivery); }
export function formalPresentation() { return formal; }
// Only actionable business validation belongs in the delivered workbench.
const businessErrors = new Set([
  'LOCAL_OUTPUT_ROOT_REQUIRED','LOCAL_OUTPUT_WRITE_FAILED','LOCAL_OUTPUT_FILE_CHANGED','OUTPUT_CONTENT_INVALID',
  'CUSTOMER_SELECTION_REQUIRED','CUSTOMER_IDENTITY_CONFLICT','CUSTOMER_ORDER_NUMBER_EXISTS',
  'PRICE_VERSION_CHANGED','PRICE_STALE','ORDER_REVISION_CHANGED','REVISION_OR_PRICE_CONFLICT',
  'QUERY_VIEW_CHANGED','CALCULATION_REQUIRED','CALCULATION_STALE',
  'OUTPUT_DELETE_FAILED_ONLY','OUTPUT_SINGLE_ORDER_TOO_LARGE','OUTPUT_SNAPSHOT_TOO_LARGE','OUTPUT_TOO_LARGE',
  'INVALID_ANALYTICS_QUERY','ANALYTICS_RANGE_TOO_LARGE',
]);
export function showError(code:string) { return !formal || businessErrors.has(code); }
