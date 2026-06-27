# Fix Plan for OpenShift OC Login TLS Handshake Timeout Issue

## Summary

This plan addresses an issue where `oc login` would fail with "net/http: TLS handshake timeout" error even when using the `--insecure-skip-tls-verify=true` flag. The problem occurred because the REST client configuration was not properly setting the insecure flag, causing TLS verification to still be attempted despite user's explicit request to skip it.

## Root Cause

The issue was in `pkg/cli/login/loginoptions.go`. When users specified `--insecure-skip-tls-verify=true`, the code was processing this flag and setting `o.InsecureTLS = true` but not passing this information down properly to the HTTP client configuration. The `clientConfig.Insecure` field was never set, so TLS verification continued to be attempted.

## Solution

Add a single line of code in `pkg/cli/login/loginoptions.go`:

```go
// if user has selected option --insecure-skip-tls-verify=true, TLS server certificate verification should not be attempted
clientConfig.Insecure = o.InsecureTLS
```

This ensures the HTTP client configuration properly honors the user's request to skip TLS verification.

## Fix Details

**File Modified**: `pkg/cli/login/loginoptions.go`
**Location**: Around line 136 in the `getClientConfig` method
**Change**: Added one line to set `clientConfig.Insecure = o.InsecureTLS`

This is a minimal, targeted fix that:
- Addresses the root cause directly
- Maintains all existing functionality
- Follows the established code patterns in the codebase
- Has no side effects or breaking changes

## Testing Approach

1. Verify that `oc login` works with `--insecure-skip-tls-verify=true` flag
2. Confirm that TLS verification still happens when flag is not used
3. Test both positive and negative cases to ensure configuration is properly handled
4. Validate that existing functionality remains unaffected

## Impact

This change ensures that cluster administrators can successfully log in to OpenShift clusters even when there are hostname or certificate mismatches, which is particularly useful for development environments or internal clusters where custom certificates are used.

The fix resolves the specific timeout issue described in GitHub issues #496 and #514.

## References

- GitHub Issue #496: https://github.com/openshift/oc/issues/496
- GitHub Pull Request #514: https://github.com/openshift/oc/pull/514