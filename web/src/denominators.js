// Mirrors api/dataset_profile.effective_roles and api/plan_builder denominator binding:
// a saved role is inserted at the front of its role list, so among resident-set Denominator
// columns the last one in the saved role order wins; a project-definition denominator that
// exists in the data beats all of them.
const SELECTABLE = ['outcome', 'numerator', 'denominator', 'grouping', 'identifier', 'pairing_id']

export function denominatorColumns(candidateRoles, columnRoles) {
  const roles = {}
  Object.entries(candidateRoles || {}).forEach(([k, v]) => { roles[k] = [...(v || [])] })
  Object.entries(columnRoles || {}).forEach(([col, raw]) => {
    const role = (raw || '').trim().toLowerCase()
    if (role === 'date' || role === 'binary') return
    SELECTABLE.forEach(r => { roles[r] = (roles[r] || []).filter(c => c !== col) })
    if (SELECTABLE.includes(role)) roles[role] = [col, ...(roles[role] || [])]
  })
  return roles.denominator || []
}

export function denominatorUsed(cols, design, colTypes) {
  const fromDesign = design?.primary_outcome?.denominator_column
  if (fromDesign && fromDesign in (colTypes || {})) return fromDesign
  return cols[0]
}
