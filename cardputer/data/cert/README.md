# CA certificate bundle

`x509_crt_bundle.bin` is a compact Mozilla root-CA bundle (esp_crt_bundle format)
embedded into the firmware and used by `HttpsTransport` via
`WiFiClientSecure::setCACertBundle` to verify the newbro server's TLS certificate.

It is vendored for reproducible builds. To regenerate (requires the python
`cryptography` package):

```bash
IDF=$(echo "$HOME"/.platformio/packages/framework-espidf*/components/mbedtls/esp_crt_bundle)
python3 "$IDF/gen_crt_bundle.py" -i "$IDF/cacrt_all.pem"   # writes ./x509_crt_bundle
cp x509_crt_bundle data/cert/x509_crt_bundle.bin
```

The embed path `data/cert/x509_crt_bundle.bin` is significant: it produces the
linker symbol `_binary_data_cert_x509_crt_bundle_bin_start` referenced in
`src/transport/HttpsTransport.cpp`.
