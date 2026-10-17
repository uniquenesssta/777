// Presentation only: the original location remains the value used by save/pick actions.
export function managedLocation(value: string, delivery: string, label: string) {
  const concealed = delivery !== "development" &&
    /(^|[^0-9.])192\.168\.4\.23(?=$|[^0-9.])/.test(value);
  return { concealed, display: concealed ? `已配置的${label}位置` : value };
}
