import bpy

for scene in bpy.data.scenes:
    scene.cycles.device = 'GPU'
    scene.render.engine = 'CYCLES'

preferences = bpy.context.user_preferences
cycles_preferences = preferences.addons["cycles"].preferences

cycles_preferences.compute_device_type = 'CUDA'

cycles_preferences.get_devices()
for d in cycles_preferences.devices:
    if d.type == 'CPU':
        d.use = False
    print("Device '{}' type {} : {}" . format(d.name, d.type, d.use))


