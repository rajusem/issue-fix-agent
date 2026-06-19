export const BlockDestructive = async (ctx) => {
  return {
    "tool.execute.before": async (input, output) => {
      if (input.tool !== "bash") return
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
  }
}
