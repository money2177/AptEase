# GitHub and submission guide

## If VS Code says Git is not recognized

If Git for Windows is installed in the default location, run these commands in a VS Code **Command Prompt** terminal to make Git available for that terminal session.

```bat
set "PATH=C:\Program Files\Git\cmd;%PATH%"
git --version
```

For PowerShell, use `$env:Path = 'C:\Program Files\Git\cmd;' + $env:Path` and then run `git --version`.

## Create and push the repository

1. Sign in to GitHub and open [New repository](https://github.com/new).
2. Set the repository name to `aptease`. Choose **Private** unless your course requires public visibility. The README contains both students’ SRNs, so confirm with your teammate and lecturer before publishing those details publicly.
3. Leave the README, .gitignore and license options unselected because you are uploading an existing project. Click **Create repository** and copy its HTTPS URL.
4. Open PowerShell in the folder containing `app.py`. Run the following commands, replacing `YOUR_USERNAME` with the repository owner’s username. Authenticate in the browser if Git prompts you.

Skip `git init -b main` if the local repository already exists.

```powershell
git init -b main
git add .
git status --short
git diff --cached --stat
git commit -m "Build apartment management DBMS project"
git remote add origin https://github.com/YOUR_USERNAME/aptease.git
git push -u origin main
```

If Git asks for author details, set them locally with `git config user.name "Aditi M Hubli"` and `git config user.email "YOUR_GITHUB_EMAIL"`, then retry the commit. Use your account’s GitHub no-reply address if you prefer to keep your email private. Check that no local database or unrelated files appear in the staged list. The included .gitignore excludes demo databases, caches and local environment files. [GitHub’s complete import instructions](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)

## Work together

1. Open the repository’s **Settings → Collaborators** and invite Fathima using her GitHub username. She accepts the invitation and runs `git clone REPOSITORY_HTTPS_URL`.
2. Before starting a new change, run `git switch main`, `git pull --ff-only`, then `git switch -c improve-demo` using a branch name that describes your change.
3. Run the app and tests, stage the changed files, commit them, and run `git push -u origin improve-demo` using the same branch name.
4. Open a pull request into `main`. Have the other teammate review and run the change before merging.
5. Give the lecturer access if the repository is private, using the submission process specified by your course.

## Before submission

- Confirm the required database engine, presentation format and any mandatory DBMS concepts in the course rubric.
- Ask your teammate to clone the repository into a separate folder and launch the project following only the README.
- Capture dashboard, billing and one operational workflow screenshot using fictional data if your submission calls for screenshots.
- Rehearse using the presentation guide. Prepare a separate local copy of the repo for the classroom demo.
- Submit the repository link and any slides, screenshots or report required by your course.
