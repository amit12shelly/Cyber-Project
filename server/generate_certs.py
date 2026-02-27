from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import datetime


def generate_self_signed_cert():
    print("Generating private key...")
    # יצירת מפתח פרטי
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    print("Generating certificate...")
    # הגדרת פרטי התעודה (תעודה בחתימה עצמית ל-localhost)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, u"localhost"),
    ])

    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        private_key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.utcnow()
    ).not_valid_after(
        # התעודה תהיה בתוקף לשנה
        datetime.datetime.utcnow() + datetime.timedelta(days=365)
    ).sign(private_key, hashes.SHA256())

    # שמירת המפתח הפרטי לקובץ key.pem
    with open("key.pem", "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))

    # שמירת התעודה לקובץ cert.pem
    with open("cert.pem", "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    print("Success! 'cert.pem' and 'key.pem' have been created in the current directory.")


if __name__ == "__main__":
    generate_self_signed_cert()