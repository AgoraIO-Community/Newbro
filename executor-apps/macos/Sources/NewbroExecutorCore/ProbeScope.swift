import Foundation

/// Families worth probing: those any profile actually uses (and that are probeable),
/// plus the Settings family currently being viewed. ACPX has no probe.
public func probeScope(profiles: [Profile], viewedFamily: String?) -> [String] {
    var families = Set<String>()
    for profile in profiles {
        if let f = profile.enabledExecutors.first, probeableExecutorFamilies.contains(f) {
            families.insert(f)
        }
    }
    if let viewed = viewedFamily, probeableExecutorFamilies.contains(viewed) {
        families.insert(viewed)
    }
    return probeableExecutorFamilies.filter { families.contains($0) }
}
