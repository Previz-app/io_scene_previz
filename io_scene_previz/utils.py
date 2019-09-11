class Active(object):
    default_team = '[Need to refresh]'
    default_name = 'Select'
    default_id = 'empty_id'

    def __init__(self):
        self.teams = [] # Structure teams.projects.scenes

    @property
    def is_refreshed(self):
        return len(self.teams) > 0

    def is_valid(self, context):
        return self.scene(context) is not None

    # Teams

    def team(self, context):
        return self.getitem(
            self.teams,
            context.scene.get('previz_active_team_id')
        )

    def team_menu_items(self):
        def cb(other, context):
            return self.menu_items(self.teams, '[No team]')
        return cb

    def team_menu_update(self):
        def cb(other, context):
            projects = self.projects(context)
            project = projects[0] if len(projects) > 0 else None
            self.set_project(context, project)
            self.log(context)
        return cb

    # Projects

    def projects(self, context):
        team = self.team(context)
        if not team:
            return []
        return team.get('projects')

    def project(self, context):
        return self.getitem(
            self.projects(context),
            context.scene.get('previz_active_project_id')
        )

    def set_project(self, context, project):
        project_id_str = str(project['id']) if project is not None else Active.default_id
        context.scene.previz_active_project_id = project_id_str

    def project_menu_items(self):
        def cb(other, context):
            return self.menu_items(self.projects(context), '[No project]')
        return cb

    def project_menu_update(self):
        def cb(other, context):
            scenes = self.scenes(context)
            scene = scenes[0] if len(scenes) > 0 else None
            self.set_scene(context, scene)
            self.log(context)
        return cb

    # Scenes

    def scenes(self, context):
        project = self.project(context)
        if not project:
            return []
        return project.get('scenes')

    def scene(self, context):
        return self.getitem(
            self.scenes(context),
            context.scene.previz_active_scene_id
        )

    def set_scene(self, context, scene):
        scene_id_str = str(scene['id']) if scene is not None else Active.default_id
        context.scene.previz_active_scene_id = scene_id_str

    def scene_menu_items(self):
        def cb(other, context):
            return self.menu_items(self.scenes(context), '[No scene]')
        return cb

    def scene_menu_update(self):
        def cb(other, context):
            self.log(context)
        return cb

    # utils

    def log(self, context):
        print('Active: team {}, project {}, scene {}'.format(
            self.as_string(self.team(context)),
            self.as_string(self.project(context)),
            self.as_string(self.scene(context))
            )
        )

    @staticmethod
    def getitem(items, id, default=None):
        for item in items:
            if item['id'] == id:
                return item
        return default

    @staticmethod
    def contains(items, id):
        for item in items:
            if item[id] == id:
                return True
        return False

    @staticmethod
    def menu_items(items, default_item_name):
        number = -1
        ret = []
        for item in items:
            name_key = Active.name_key(item)

            id   = item['id']
            name = item[name_key]
            number += 1
            ret.append((id, name, name, number))
        if len(ret) == 0:
            number += 1
            item = (Active.default_id, default_item_name, default_item_name, number)
            ret.append(item)
        return ret

    @staticmethod
    def as_string(item):
        if item is None:
            return str(None)
        name_key = Active.name_key(item)
        return '{}[id:{}]'.format(item[name_key], item['id'])

    @staticmethod
    def name_key(item):
        if 'title' in item:
            return 'title'
        return 'name'

    @staticmethod
    def as_id(prop):
        if prop == '':
            return -1
        return int(prop)


def extract(data, next_name = None):
    ret = {
        'id': data['id'],
        'title': data['title']
    }
    if next_name is None:
        return ret

    ret[next_name] = []
    return ret, ret[next_name]


def extract_all(teams_data):
    teams = []
    for t in teams_data:
        team, projects = extract(t, 'projects')
        teams.append(team)
        for p in t['projects']:
            project, scenes = extract(p, 'scenes')
            projects.append(project)
            for s in p['scenes']:
                scene = extract(s)
                scenes.append(scene)
    return teams
