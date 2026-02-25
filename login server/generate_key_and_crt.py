from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from datetime import datetime, timedelta

# 1. יצירת מפתח פרטי (RSA)
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

# 2. יצירת פרטי התעודה (מזהה את השרת כ-localhost)
subject = issuer = x509.Name([
    x509.NameAttribute(NameOID.COMMON_NAME, u"localhost"),
])

# 3. בניית התעודה (תקיפה לשנה אחת)
cert = x509.CertificateBuilder().subject_name(
    subject
).issuer_name(
    issuer
).public_key(
    key.public_key()
).serial_number(
    x509.random_serial_number()
).not_valid_before(
    datetime.utcnow()
).not_valid_after(
    datetime.utcnow() + timedelta(days=365)
).sign(key, hashes.SHA256())

# 4. שמירת המפתח לקובץ server.key
with open("server.key", "wb") as f:
    f.write(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ))

# 5. שמירת התעודה לקובץ server.crt
with open("server.crt", "wb") as f:
    f.write(cert.public_bytes(serialization.Encoding.PEM))

print("Created server.key and server.crt successfully!")