# Chantal Proof of Concept Scripts

## RHEL CDN Authentication Test

**Datei:** `rhel-cdn-auth-test.py`

### Zweck

Validiert, dass wir mit Python's `requests` Library und subscription-manager Zertifikaten erfolgreich:
1. ✅ Red Hat CDN erreichen können
2. ✅ Mit Client-Zertifikaten authentifizieren können
3. ✅ Repository-Metadaten (repomd.xml) downloaden können
4. ✅ RPM-Pakete downloaden können

### Voraussetzungen

**RHEL-System mit aktiver Subscription:**

```bash
# Check subscription status
subscription-manager status

# Should show:
# Overall Status: Current
# System Purpose Status: Matched

# If not registered:
subscription-manager register --username YOUR_USERNAME
subscription-manager attach --auto
```

**Python 3.6+ mit requests:**

```bash
# RHEL 9
sudo dnf install python3-requests

# Or via pip
pip3 install requests
```

### Ausführen

```bash
# Als root (braucht Zugriff auf /etc/pki/entitlement/)
sudo python3 rhel-cdn-auth-test.py

# Oder mit eigenem User wenn Zugriff auf Zertifikate
python3 rhel-cdn-auth-test.py
```

### Erwartete Ausgabe

```
======================================================================
RHEL CDN Authentication - Proof of Concept Test
======================================================================

======================================================================
Step 1: Finding Entitlement Certificates
======================================================================
✓ SUCCESS: Found certificate: 1234567890123456789.pem
✓ SUCCESS: Found key file: 1234567890123456789-key.pem

======================================================================
Step 2: Verifying CA Certificate
======================================================================
✓ SUCCESS: CA certificate found: /etc/rhsm/ca/redhat-uep.pem

======================================================================
Step 3: Testing Connection to Red Hat CDN
======================================================================
ℹ INFO: Connecting to: https://cdn.redhat.com/...
ℹ INFO: Using cert: 1234567890123456789.pem
ℹ INFO: Using key: 1234567890123456789-key.pem
ℹ INFO: Using CA: redhat-uep.pem
✓ SUCCESS: Successfully connected! Status: 200
ℹ INFO: Response size: 4523 bytes

======================================================================
Step 4: Downloading Repository Metadata (repomd.xml)
======================================================================
✓ SUCCESS: Downloaded repomd.xml (4523 bytes)
✓ SUCCESS: repomd.xml is valid XML
ℹ INFO: Found primary.xml at: repodata/abc123-primary.xml.gz

======================================================================
Step 5: Downloading Test RPM Package
======================================================================
ℹ INFO: Attempting to download: basesystem RPM
✓ SUCCESS: Successfully downloaded RPM package!
✓ SUCCESS: RPM magic bytes verified (0xED 0xAB 0xEE 0xDB)

======================================================================
Step 6: Testing Other RHEL Repositories
======================================================================
✓ SUCCESS: AppStream: Accessible
ℹ INFO: BaseOS Debug: Not found (may not be entitled)

======================================================================
SUMMARY
======================================================================
✓ Certificate Discovery: PASSED
✓ CDN Connection: PASSED
✓ Metadata Download: PASSED
✓ Authentication: WORKING

🎉 SUCCESS: Chantal will be able to sync from RHEL CDN!
======================================================================
```

### Fehler-Szenarien

#### Keine Subscription

```
✗ ERROR: No entitlement certificates found
ℹ INFO: Run: subscription-manager register
ℹ INFO: Then: subscription-manager attach --auto
```

**Lösung:**
```bash
subscription-manager register --username YOUR_USERNAME
subscription-manager attach --auto
```

#### Abgelaufene Subscription

```
✗ ERROR: SSL Error: ...certificate verify failed...
ℹ INFO: Certificate may be invalid or expired
```

**Lösung:**
```bash
subscription-manager refresh
subscription-manager attach --auto
```

#### Kein Zugriff auf Zertifikate

```
✗ ERROR: Entitlement directory not found: /etc/pki/entitlement
```

**Lösung:**
```bash
# Als root ausführen
sudo python3 rhel-cdn-auth-test.py
```

### Was validiert wird

| Check | Validiert | Relevant für Chantal |
|-------|-----------|---------------------|
| **Cert Discovery** | subscription-manager Zertifikate finden | Config-Loader muss Certs finden können |
| **TLS Connection** | HTTPS mit Client-Certs funktioniert | Download-Manager braucht TLS |
| **repomd.xml** | Metadata-Download klappt | Plugin muss repomd.xml parsen |
| **RPM Download** | Echte Pakete downloadbar | Sync muss RPMs downloaden können |
| **Multi-Repo** | Verschiedene Repos zugreifbar | Chantal soll mehrere Repos syncen |

### Nächste Schritte nach erfolgreichem Test

1. ✅ **Validiert:** Python `requests` + Client-Certs funktioniert
2. ✅ **Validiert:** Red Hat CDN ist erreichbar
3. ➡️ **Nächster PoC:** repomd.xml parsen + primary.xml.gz verarbeiten
4. ➡️ **Nächster PoC:** Content-Addressed Storage testen

### Troubleshooting

**Netzwerk-Probleme:**
```bash
# Test CDN Erreichbarkeit
curl -I https://cdn.redhat.com

# DNS Check
nslookup cdn.redhat.com

# Proxy-Konfiguration?
echo $http_proxy
echo $https_proxy
```

**Zertifikat-Probleme:**
```bash
# Liste Zertifikate
ls -la /etc/pki/entitlement/

# Check Zertifikat-Gültigkeit
openssl x509 -in /etc/pki/entitlement/*.pem -noout -dates

# Subscription-Status
subscription-manager status
subscription-manager list
```

**Python-Probleme:**
```bash
# Check Python Version
python3 --version

# Install requests
pip3 install --user requests

# Test import
python3 -c "import requests; print(requests.__version__)"
```

## Weitere PoC-Scripts (folgen)

- `poc/parse-repomd.py` - repomd.xml + primary.xml Parser
- `poc/content-addressed-storage.py` - SHA256 Pool Implementierung
- `poc/rpm-metadata-extract.py` - RPM-Metadaten extrahieren

