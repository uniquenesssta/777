// Windows .NET Framework only; certificate callbacks never enter PowerShell threads.
using System;
using System.IO;
using System.Net;
using System.Net.Security;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;

namespace Quote777 {
    public sealed class ProbeResult {
        public bool Tcp;
        public string Https = "not_checked";
        public int HttpStatus;
        public string Error;
    }
    public static class HostProbe {
        public static ProbeResult Check(string origin, string pin) {
            Uri uri = new Uri(origin);
            if (uri.Scheme != "https" || uri.UserInfo != "" || uri.AbsolutePath != "/" || uri.Query != "" || uri.Fragment != "")
                throw new InvalidOperationException("HOST_PROBE_URL_INVALID");
            ProbeResult result = new ProbeResult();
            using (TcpClient tcp = new TcpClient()) {
                IAsyncResult pending = tcp.BeginConnect(uri.Host, uri.Port, null, null);
                using (System.Threading.WaitHandle handle = pending.AsyncWaitHandle) {
                    if (!handle.WaitOne(2000)) { result.Error = "HOST_PORT_UNREACHABLE"; return result; }
                    try { tcp.EndConnect(pending); result.Tcp = true; }
                    catch (SocketException) { result.Error = "HOST_PORT_UNREACHABLE"; return result; }
                }
            }
            if (String.IsNullOrEmpty(pin)) { result.Https = "public_connection_required"; return result; }
            if (!System.Text.RegularExpressions.Regex.IsMatch(pin, "^[a-f0-9]{64}$"))
                throw new InvalidOperationException("HOST_PROBE_PIN_INVALID");
            HttpWebRequest request = (HttpWebRequest)WebRequest.Create(new Uri(uri, "/v1/capabilities"));
            request.Proxy = null;
            request.AllowAutoRedirect = false;
            request.Timeout = 3000;
            request.ReadWriteTimeout = 3000;
            request.KeepAlive = false;
            // An unknown syntactically valid token tests the normal unauthenticated path.
            request.Headers[HttpRequestHeader.Authorization] = "Bearer " + new string('A', 43);
            bool verified = false;
            request.ServerCertificateValidationCallback = delegate(object sender, X509Certificate cert, X509Chain chain, SslPolicyErrors errors) {
                if (cert == null || (errors & (SslPolicyErrors.RemoteCertificateNameMismatch | SslPolicyErrors.RemoteCertificateNotAvailable)) != 0) return false;
                using (SHA256 sha = SHA256.Create()) {
                    string actual = BitConverter.ToString(sha.ComputeHash(cert.GetRawCertData())).Replace("-", "").ToLowerInvariant();
                    verified = actual == pin;
                    return verified;
                }
            };
            SecurityProtocolType prior = ServicePointManager.SecurityProtocol;
            HttpWebResponse response = null;
            try {
                ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
                try { response = (HttpWebResponse)request.GetResponse(); }
                catch (WebException error) {
                    response = error.Response as HttpWebResponse;
                    if (response == null) { result.Https = "failed"; result.Error = "HOST_HTTPS_CONNECTION_FAILED"; return result; }
                }
                result.HttpStatus = (int)response.StatusCode;
                using (Stream stream = response.GetResponseStream()) {
                    byte[] buffer = new byte[65537]; int count = 0, read;
                    while (count < buffer.Length && (read = stream.Read(buffer, count, buffer.Length - count)) > 0) count += read;
                    string body = Encoding.UTF8.GetString(buffer, 0, count);
                    if (verified && result.HttpStatus == 401 && count < buffer.Length && body.Trim() == "{\"error\":\"UNAUTHENTICATED\"}") {
                        result.Https = "verified_response";
                    } else { result.Https = "unexpected_response"; result.Error = "HOST_HTTPS_UNEXPECTED_RESPONSE"; }
                }
            } catch (WebException) { result.Https = "failed"; result.Error = "HOST_HTTPS_CONNECTION_FAILED"; }
            finally {
                if (response != null) response.Dispose();
                request.Abort();
                ServicePointManager.SecurityProtocol = prior;
            }
            return result;
        }
    }
}
