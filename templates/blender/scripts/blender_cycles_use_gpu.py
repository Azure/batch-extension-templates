import bpy

for scene in bpy.data.scenes:
    scene.cycles.device = 'GPU'
    scene.render.engine = 'CYCLES'


preferences = bpy.context.preferences
cycles_preferences = preferences.addons["cycles"].preferences
devices = cycles_preferences.get_devices()

cycles_preferences.compute_device_type = 'CUDA'


print("set scene.cycles.device and scene.render.engine")


for d in devices:
    if d.type == 'CPU':
        d.use = False
    print("Device '{}' type {} : {}" . format(d.name, d.type, d.use))


