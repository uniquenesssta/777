"""Check both formal package permissions and the independent Host role boundary."""
from quote_service.protocol import APIError


def check_sales_backup_denied(sales, host):
    for action in ['backup', 'backup_status']:
        response = sales.call(action)
        assert 'error' in response, (action, response)
        error = response['error']
        assert error['status'] == 403 and error['code'] == 'PACKAGE_PERMISSION_DENIED', (action, error)

    # Bypass desktop IPC to prove that the Host still rejects the sales role.
    client = host.client('sales-one')
    try:
        for method, body in [('GET', None), ('POST', {'kind': 'daily'})]:
            try:
                client.request(method, '/v1/backup', body)
            except APIError as error:
                assert error.status == 403 and error.code == 'FORBIDDEN', (method, str(error))
            else:
                raise AssertionError('SALES_HOST_BACKUP_ACCESS_ACCEPTED: ' + method)
    finally:
        client.logout()
