"""审批合同的标准库例子；不包含真实认证系统。"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Approval:
    approved: bool
    proposal_hash: str
    owner: str
    expires_at: int

def check(a: Approval, expected_hash: str, trusted_owner: str, now: int, cancelled: bool = False) -> str:
    if cancelled:
        return "cancelled"
    if not a.approved:
        return "rejected"
    if a.owner != trusted_owner:
        return "unauthorized"
    if a.expires_at <= now:
        return "expired"
    if a.proposal_hash != expected_hash:
        return "stale_approval"
    return "approved"

def main() -> None:
    a = Approval(True, "proposal-v1", "alice", 200)
    outcomes = [check(a, "proposal-v1", "alice", 100),
                check(a, "proposal-v2", "alice", 100),
                check(a, "proposal-v1", "alice", 100, cancelled=True),
                check(a, "proposal-v1", "bob", 100)]
    assert outcomes == ["approved", "stale_approval", "cancelled", "unauthorized"]
    print("\n".join(outcomes))

if __name__ == "__main__":
    main()
