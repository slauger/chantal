# SSL/TLS and Authentication

Chantal supports SSL/TLS client certificates for authenticating with subscription-based repositories like Red Hat CDN.

## Overview

SSL/TLS settings can be configured:
- **Globally** (applies to all repositories)
- **Per-repository** (overrides global settings)

## Global SSL Configuration

Applied to all repositories unless overridden:

```yaml
ssl:
  ca_bundle: /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem
  verify: true
```

## Per-Repository SSL Configuration

Override global settings for specific repositories:

```yaml
repositories:
  - id: rhel9-baseos
    type: rpm
    feed: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os
    ssl:
      ca_bundle: /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem
      client_cert: /etc/pki/entitlement/1234567890.pem
      client_key: /etc/pki/entitlement/1234567890-key.pem
      verify: true
```

## SSL Options

### CA Bundle

Path to CA certificate bundle for verifying server certificates:

```yaml
ssl:
  ca_bundle: /path/to/ca-bundle.pem
```

**Default locations:**
- RHEL/CentOS/Rocky: `/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem`
- Debian/Ubuntu: `/etc/ssl/certs/ca-certificates.crt`

### Client Certificate

Path to client certificate for mutual TLS authentication:

```yaml
ssl:
  client_cert: /etc/pki/entitlement/1234567890.pem
```

Required for Red Hat CDN access.

### Client Key

Path to private key for client certificate:

```yaml
ssl:
  client_key: /etc/pki/entitlement/1234567890-key.pem
```

**Note:** Key must be unencrypted (no passphrase).

### Verify Server Certificate

Whether to verify server SSL certificate:

```yaml
ssl:
  verify: true  # Recommended for production
```

**Options:**
- `true` - Verify server certificate (default, recommended)
- `false` - Skip verification (insecure, for testing only)

## RHEL Subscription Setup

Red Hat CDN requires client certificate authentication.

### Method 1: Using subscription-manager (Recommended)

Register your system with Red Hat:

```bash
# Register system
sudo subscription-manager register --username YOUR_USERNAME

# Attach subscription
sudo subscription-manager attach --auto

# List entitlement certificates
sudo ls -la /etc/pki/entitlement/
```

**Output:**
```
-rw-r--r--. 1 root root 3243 Jan 10 10:00 1234567890.pem
-rw-r--r--. 1 root root 1704 Jan 10 10:00 1234567890-key.pem
```

Configure Chantal to use these certificates:

```yaml
repositories:
  - id: rhel9-baseos
    name: RHEL 9 BaseOS
    type: rpm
    feed: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os
    ssl:
      ca_bundle: /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem
      client_cert: /etc/pki/entitlement/1234567890.pem
      client_key: /etc/pki/entitlement/1234567890-key.pem
      verify: true
```

### Method 2: Manual Certificate Download

Download certificates from Red Hat Customer Portal:

1. Log in to https://access.redhat.com/
2. Navigate to Subscriptions
3. Download certificate and key
4. Place in secure location:
   ```bash
   sudo mkdir -p /etc/pki/chantal
   sudo cp rhel-cert.pem /etc/pki/chantal/
   sudo cp rhel-key.pem /etc/pki/chantal/
   sudo chmod 600 /etc/pki/chantal/rhel-key.pem
   ```

5. Configure Chantal:
   ```yaml
   repositories:
     - id: rhel9-baseos
       ssl:
         client_cert: /etc/pki/chantal/rhel-cert.pem
         client_key: /etc/pki/chantal/rhel-key.pem
   ```

### Method 3: Shared Entitlement (Development)

For development/testing, copy certificates from registered system:

```bash
# On registered RHEL system
sudo tar czf entitlement.tar.gz /etc/pki/entitlement/

# On Chantal system
tar xzf entitlement.tar.gz
```

**⚠️ Warning:** Ensure compliance with Red Hat subscription terms.

## Complete RHEL Configuration Example

```yaml
repositories:
  # RHEL 9 BaseOS
  - id: rhel9-baseos
    name: RHEL 9 BaseOS
    type: rpm
    feed: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os
    enabled: true
    ssl:
      ca_bundle: /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem
      client_cert: /etc/pki/entitlement/1234567890.pem
      client_key: /etc/pki/entitlement/1234567890-key.pem
      verify: true
    filters:
      metadata:
        architectures:
          include: ["x86_64", "noarch"]
      rpm:
        exclude_source_rpms: true

  # RHEL 9 AppStream
  - id: rhel9-appstream
    name: RHEL 9 AppStream
    type: rpm
    feed: https://cdn.redhat.com/content/dist/rhel9/9/x86_64/appstream/os
    enabled: true
    ssl:
      ca_bundle: /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem
      client_cert: /etc/pki/entitlement/1234567890.pem
      client_key: /etc/pki/entitlement/1234567890-key.pem
      verify: true
    filters:
      metadata:
        architectures:
          include: ["x86_64", "noarch"]
      rpm:
        exclude_source_rpms: true
```

## Self-Signed Certificates

For internal repositories with self-signed certificates:

### Option 1: Add to System Trust Store (Recommended)

```bash
# RHEL/CentOS/Rocky
sudo cp internal-ca.crt /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust

# Debian/Ubuntu
sudo cp internal-ca.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates
```

Chantal will automatically use system trust store.

### Option 2: Custom CA Bundle

```yaml
repositories:
  - id: internal-repo
    type: rpm
    feed: https://internal.example.com/repo
    ssl:
      ca_bundle: /etc/pki/chantal/internal-ca-bundle.pem
      verify: true
```

### Option 3: Disable Verification (Not Recommended)

```yaml
repositories:
  - id: internal-repo
    type: rpm
    feed: https://internal.example.com/repo
    ssl:
      verify: false  # Insecure!
```

**⚠️ Warning:** Only use for testing. Never in production.

## Troubleshooting

### Certificate Errors

```
Error: SSL certificate verification failed
```

**Solutions:**
1. Check CA bundle path is correct
2. Verify server certificate is valid
3. Ensure system time is correct
4. Update CA certificates: `sudo update-ca-trust`

### Client Certificate Errors

```
Error: Client certificate authentication failed
```

**Solutions:**
1. Verify client_cert and client_key paths are correct
2. Check certificate has not expired
3. Ensure key is unencrypted (no passphrase)
4. Verify subscription is active

### Permission Errors

```
Error: Permission denied: /etc/pki/entitlement/1234567890-key.pem
```

**Solutions:**
```bash
# Fix permissions
sudo chmod 644 /etc/pki/entitlement/1234567890.pem
sudo chmod 600 /etc/pki/entitlement/1234567890-key.pem

# Or copy to user-accessible location
mkdir -p ~/.config/chantal/certs
sudo cp /etc/pki/entitlement/* ~/.config/chantal/certs/
sudo chown $USER:$USER ~/.config/chantal/certs/*
chmod 600 ~/.config/chantal/certs/*-key.pem
```

### Check Certificate Validity

```bash
# View certificate details
openssl x509 -in /etc/pki/entitlement/1234567890.pem -text -noout

# Check expiration
openssl x509 -in /etc/pki/entitlement/1234567890.pem -noout -dates

# Test connection
curl --cert /etc/pki/entitlement/1234567890.pem \
     --key /etc/pki/entitlement/1234567890-key.pem \
     https://cdn.redhat.com/content/dist/rhel9/9/x86_64/baseos/os/repodata/repomd.xml
```

## Security Best Practices

1. **Protect private keys:**
   ```bash
   chmod 600 /path/to/key.pem
   ```

2. **Use system trust store:** Prefer system CA bundles over custom bundles

3. **Always verify certificates:** Never set `verify: false` in production

4. **Rotate certificates:** Monitor expiration dates, rotate before expiry

5. **Limit access:** Only grant access to users who need it

6. **Audit usage:** Track who has access to subscription certificates
