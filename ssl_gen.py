"""
ssl_gen.py — self-signed TLS cert with SAN (Chrome-compatible)
Chrome requirements: SAN present, SHA-256, RSA>=2048, validity <=398 days.
Regenerates automatically if cert is missing or expires within 30 days.
"""
import datetime, ipaddress, json, logging, os, subprocess
from pathlib import Path
from cryptography import x509
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

_SD           = Path(os.environ.get("TC_LAB_STATE_DIR", "."))
CERT_FILE     = _SD / "cert.pem"
KEY_FILE      = _SD / "key.pem"
VALIDITY_DAYS = 397          # Chrome hard limit is 398

logger = logging.getLogger(__name__)

def _get_local_ips():
    """Collect all IPv4 addresses on this host to add as SAN IPs."""
    ips = {"127.0.0.1"}
    try:
        r = subprocess.run(["ip", "-j", "addr"], capture_output=True, text=True)
        for iface in json.loads(r.stdout):
            for ai in iface.get("addr_info", []):
                if ai.get("family") == "inet":
                    ips.add(ai["local"])
    except Exception:
        pass
    return sorted(ips)

def _needs_regen():
    if not CERT_FILE.exists() or not KEY_FILE.exists():
        return True
    try:
        cert = x509.load_pem_x509_certificate(CERT_FILE.read_bytes())
        remaining = (cert.not_valid_after_utc -
                     datetime.datetime.now(datetime.timezone.utc)).days
        if remaining < 30:
            logger.warning("TLS cert expires in %d days — regenerating", remaining)
            return True
        logger.info("TLS cert OK — valid for %d more days", remaining)
        return False
    except Exception:
        return True

def ensure_cert():
    """Generate cert + key if missing or expiring. Returns (cert_path, key_path)."""
    _SD.mkdir(parents=True, exist_ok=True)
    if not _needs_regen():
        return str(CERT_FILE), str(KEY_FILE)

    logger.info("Generating self-signed TLS certificate...")
    ips = _get_local_ips()
    logger.info("  SANs: localhost, tc-lab.local + IPs: %s", ips)

    key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend())

    san = x509.SubjectAlternativeName(
        [x509.DNSName("localhost"), x509.DNSName("tc-lab.local")] +
        [x509.IPAddress(ipaddress.IPv4Address(ip)) for ip in ips])

    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME,        "TC Lab"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME,  "TC Lab Self-Signed"),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)

    cert = (x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=VALIDITY_DAYS))
        .add_extension(san, critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, key_cert_sign=True, crl_sign=True,
            content_commitment=False, key_encipherment=True, data_encipherment=False,
            key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage(
            [ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256(), default_backend()))

    KEY_FILE.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    KEY_FILE.chmod(0o600)
    CERT_FILE.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    logger.info("cert.pem + key.pem written.")
    logger.info(">>> To avoid Chrome warning: chrome://settings/certificates")
    logger.info("    Authorities tab -> Import cert.pem -> Trust for HTTPS")
    return str(CERT_FILE), str(KEY_FILE)
