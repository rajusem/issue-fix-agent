export const BlockDestructive = async (ctx) => {
  const SECRET_PATTERNS = [
    /AKIA[0-9A-Z]{16}/,
    /AIza[0-9A-Za-z_-]{35}/,
    /ghp_[0-9a-zA-Z]{36}/,
    /gho_[0-9a-zA-Z]{36}/,
    /github_pat_[0-9a-zA-Z_]{82}/,
    /glpat-[0-9a-zA-Z_-]{20}/,
    /sk-[0-9a-zA-Z]{48}/,
    /xox[bpors]-[0-9a-zA-Z-]+/,
    /ATATT[0-9a-zA-Z_/+=]{50,}/,
    /-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----/,
  ]

  return {
    "tool.execute.before": async (input, output) => {
      if (input.tool === "bash") {
        const cmd = output.args?.command || ""

        if (/git (push --force|reset --hard|checkout \.|clean -fd)/.test(cmd)) {
          throw new Error("BLOCKED: Destructive git operation")
        }
        if (/rm -rf \/|chmod 777|> \/dev\//.test(cmd)) {
          throw new Error("BLOCKED: Dangerous command")
        }
        if (/gh pr (review --approve|merge)/.test(cmd)) {
          throw new Error("BLOCKED: PR approval/merge must be done by humans")
        }
      }

      if (input.tool === "edit" || input.tool === "write") {
        const content = output.args?.content || output.args?.new_string || ""
        for (const pattern of SECRET_PATTERNS) {
          if (pattern.test(content)) {
            throw new Error("BLOCKED: Content matches secret pattern — " + pattern.source)
          }
        }
      }
    }
  }
}
