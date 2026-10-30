---
name: Receive or build failure
about: Report a reproducible failure with identities and a bounded log
---

## Problem and expected behavior

## Version and environment

- Source commit / changed files:
- Firmware generation and manifest:
- Host component and paired DLL:
- OS / Python / compiler / SDR application:
- Device/interface identity (redact private serials):

## Reproduction

Give the smallest command or UI sequence. For streaming include centerHz, BW/Fs, gain index, Auto route if known, duration and other device consumers.

## Evidence

Attach the small final JSON/status, error and drain result. Distinguish a hardware run from a mock/emulator. Include device/host/consumer byte counts; do not attach largeIQ, PAC, SDK or personal paths by default.

## What changed between working and failing

