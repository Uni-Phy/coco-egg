"""A self-signed certificate, because a browser will not open a microphone without one.

`getUserMedia` is gated on a secure context. On `http://172.20.10.2:8090` every
modern browser refuses the microphone outright — not a prompt the user can
accept, a flat refusal. So a phone can only be the egg's microphone over HTTPS,
and on a LAN with no domain name that means a certificate we make ourselves.

The cost is honest and unavoidable: the first visit shows a "not private"
warning that has to be tapped through once. There is no way around it short of a
real domain and a real CA, which an offline classroom device does not have.

Generated once into state/ and reused, so the warning is accepted once per
device rather than once per restart — a certificate regenerated on every boot
would retrain people to click through warnings, which is the wrong habit to
teach even for a demo.
"""
from __future__ import annotations

import pathlib
import subprocess

# 825 days is the maximum most browsers accept for a leaf certificate; longer
# and some refuse it outright rather than merely warning.
DAYS = 820


def ensure(cert_dir: str, hosts: list[str]) -> tuple[str, str] | None:
    """Return (cert, key) paths, generating them if absent. None if we cannot.

    Never raises: a console that cannot make a certificate should fall back to
    plain HTTP and say so, not stop the device from teaching.
    """
    d = pathlib.Path(cert_dir)
    cert, key = d / "console-cert.pem", d / "console-key.pem"
    if cert.is_file() and key.is_file():
        return str(cert), str(key)

    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"  console: cannot write {cert_dir} ({e.__class__.__name__})", flush=True)
        return None

    # Every address the device might be reached on goes in as a SAN. A browser
    # matches the certificate against the URL it was given, so a cert naming
    # only one IP fails the moment the device moves network — which this device
    # does, between a WiFi and a phone hotspot.
    sans = ",".join(
        f"IP:{h}" if h.replace(".", "").isdigit() else f"DNS:{h}" for h in hosts
    )
    try:
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
             "-keyout", str(key), "-out", str(cert), "-days", str(DAYS),
             "-subj", "/CN=coco-egg", "-addext", f"subjectAltName={sans}"],
            check=True, capture_output=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as e:
        print(f"  console: certificate generation failed ({e.__class__.__name__})",
              flush=True)
        return None
    try:
        key.chmod(0o600)
    except OSError:
        pass
    print(f"  console: generated a self-signed certificate for {sans}", flush=True)
    return str(cert), str(key)


def local_addresses(extra: list[str] | None = None) -> list[str]:
    """Every address this device might answer on, for the certificate SANs.

    `hostname -I` runs INSIDE the container and returns the container's address,
    not the host's — so the LAN address a phone actually types is invisible from
    here. That produced a certificate naming 172.18.0.5 and not 10.10.10.186,
    and a name mismatch is a harsher browser warning than a plain self-signed
    one. Hence `console.cert_hosts`: the addresses the device is reached on,
    which only the operator knows.

    The device also moves between a WiFi network and a phone hotspot, so both
    common hotspot ranges are included up front — moving network should not mean
    a new certificate and a warning to accept again.
    """
    hosts = ["localhost", "127.0.0.1", "coco-egg.local"] + list(extra or [])
    try:
        out = subprocess.run(["hostname", "-I"], capture_output=True, text=True,
                             timeout=5).stdout
        hosts += [ip for ip in out.split() if ip.count(".") == 3]
    except (OSError, subprocess.SubprocessError):
        pass
    # Both common phone-hotspot ranges, so moving to one does not need a new
    # certificate: iOS hands out 172.20.10.x, Android 192.168.43.x.
    hosts += [f"172.20.10.{i}" for i in range(2, 15)]
    hosts += [f"192.168.43.{i}" for i in range(2, 20)]
    return list(dict.fromkeys(hosts))
