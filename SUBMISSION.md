# Submission evidence checklist

The user requested a complete codebase, GitHub URL, continuous contribution history, architecture document, and performance report. The codebase and local reports are in this directory. The remaining fields require authentic team-owned information.

| Item | Status | Required action |
|---|---|---|
| GitHub repository URL | Pending | Provide the team's repository URL or credentials/access to create it. |
| Significant contributions by each member throughout the half-semester | Cannot be reconstructed from this newly created directory | All members must actually commit code throughout the period; use `git shortlog -sne --all` and `git log --date=short --pretty=format:'%h %ad %an %s'` for verification. |
| Git history screenshots | Pending real history | Capture the repository's real commit graph and author/date details after genuine work. Do not fabricate or backdate commits. |
| Architecture | Complete for current prototype | Review `ARCHITECTURE.md` against live deployment. |
| Course mid/final set metrics | Pending datasets and team API key | Execute the released sets and record raw outputs, rubric scores, times, failure categories and memory snapshots. |

The saved course page also requires a week-13 presentation. Prepare slides from verified results when those results exist.

## Create the team repository

Create an empty GitHub repository under a team-controlled account. From this project directory, each contributor should use their real Git identity. The first contributor can run:

```powershell
git init
git add .
git commit -m "Build initial multi-agent prototype"
git branch -M main
git remote add origin https://github.com/OWNER/REPOSITORY.git
git push -u origin main
```

Replace `OWNER/REPOSITORY` with the actual repository. Invite team members with write access. Each person should work and commit throughout the remaining project period. Preserve the actual commit dates and authors when producing screenshots for submission.
