# <img src="https://media2.giphy.com/media/QssGEmpkyEOhBCb7e1/giphy.gif?cid=ecf05e47a0n3gi1bfqntqmob8g9aid1oyj2wr3ds3mg700bl&rid=giphy.gif" alt="git admin" width="40" /> Project Manager

A web application to manage multiple Git projects from a single interface. Add your local project directories and perform Git operations like checking status, switching branches, and pulling changes.


## Usage

1. **Add a Project**: Click the "+ Add Project" button:
   - **Swipe/Drag** or click dots to switch between pages
   - **Page 1**: Add existing project by entering its path
   - **Page 2**: Clone from URL - enter clone path + repository URL (GitHub/GitLab/etc.)

2. **View Project Actions**: Click on any project card (or the three dots menu) to see available Git operations.
   - You can also **drag & drop cards** to reorder them (order is saved).

3. **Git Operations**:
   - **Show Git Status**: View the current branch and repository status
   - **Switch Branch**: Enter a branch name to checkout
   - **Pull Changes**: Pull the latest changes from the remote repository

4. **Odoo Config**: Click **Odoo Config** → first time it asks for your `odoo.conf` path (custom popup), then it will open it directly on future clicks.

5. **Restore DB Docker**: Click **Restore DB Docker**, then pick a backup **folder** or **`.zip`** (browse icon, or paste the path). Restores into Postgres on `localhost:5435` (`dump.sql` + optional `filestore`).
   - Browse icon → `.zip` · **Shift+click** → folder

## API Endpoints

- `GET /api/projects` - Get all projects
- `POST /api/projects` - Add a new project
- `POST /api/projects/clone` - Clone repository and add as project
- `DELETE /api/projects/<id>` - Delete a project
- `GET /api/projects/<id>/links` - Get links for a project
- `PUT /api/projects/<id>/links` - Update links for a project
- `GET /api/projects/<id>/git-status` - Get Git status
- `POST /api/projects/<id>/checkout` - Switch branch
- `POST /api/projects/<id>/pull` - Pull chang
- `POST /api/projects/reorder` - Save card order
- `GET /api/settings/odoo-config-path` - Get saved Odoo config path
- `POST /api/settings/odoo-config-path` - Save Odoo config path
- `POST /api/docker-restore/detect` - Detect backup folder/zip
- `POST /api/docker-restore/browse` - Native file/folder picker
- `POST /api/docker-restore/restore-stream` - Restore into Docker Postgres (SSE)

## Notes

- Projects are stored in `projects.json` file
- Settings (like Odoo config path) are stored in `settings.json`
- The application verifies that project paths exist before adding them
- All Git operations are executed in the project's directory
- Docker restore expects an Odoo-style backup with `dump.sql` (optional `filestore/`)

- "Open on GitHub/GitLab" is detected from the repo remote URL
