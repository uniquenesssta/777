// Apply to formal package creation; verification fixtures may still use publicConnection directly.
export function requireNetworkTarget(connection) {
  const host = new URL(connection.url).hostname.toLowerCase().replace(/^\[|\]$/g, '').replace(/\.$/, '');
  if (host === 'localhost' || host.endsWith('.localhost') || /^127\./.test(host) || host === '0.0.0.0' || host === '::' || host === '::1' || /^::ffff:(7f[0-9a-f]{2}:|0:0$)/.test(host)) {
    throw Error('PACKAGE_LOOPBACK_FORBIDDEN');
  }
  return connection;
}
