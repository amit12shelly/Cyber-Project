import datetime
import ipaddress

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# 1. Generate Private Key
key = rsa.generate_private_key(public_exponent=65537, key_size=4096)

# 2. Define Certificate details
# Change the Common Name to your IP
subject = issuer = x509.Name([
    x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
    x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "CA"),
    x509.NameAttribute(NameOID.LOCALITY_NAME, "Test"),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "My QUIC Server"),
    x509.NameAttribute(NameOID.COMMON_NAME, "10.12.9.203"), # <-- Change this
])

# Add the IP address to the extensions
cert = x509.CertificateBuilder().subject_name(
    subject
).issuer_name(
    issuer
).public_key(
    key.public_key()
).serial_number(
    x509.random_serial_number()
).not_valid_before(
    datetime.datetime.utcnow()
).not_valid_after(
    datetime.datetime.utcnow() + datetime.timedelta(days=365)
).add_extension(
    x509.SubjectAlternativeName([
        x509.DNSName("localhost"),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),# <-- Add this line
        x509.IPAddress(ipaddress.IPv4Address("10.12.9.203"))
    ]),
    critical=False,
).sign(key, hashes.SHA256())

# 3. Write files
with open("server/key.pem", "wb") as f:
    f.write(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ))

with open("cert.pem", "wb") as f:
    f.write(cert.public_bytes(serialization.Encoding.PEM))

print("Success! cert.pem and key.pem have been created.")