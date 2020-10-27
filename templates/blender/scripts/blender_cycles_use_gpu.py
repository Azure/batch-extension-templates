import bpy

print("Loaded: ", bpy.data.filepath)
print(bpy.app.version_string)
 
preferences = bpy.context.preferences
cycles_preferences = preferences.addons["cycles"].preferences
 
cycles_preferences.get_devices()
for d in cycles_preferences.devices:
    if d.type == 'CPU':
        d.use = False
    print("Device '{}' type {} : {}" . format(d.name, d.type, d.use))
 
cycles_preferences.compute_device_type = 'CUDA'
 
for scene in bpy.data.scenes:
    scene.render.tile_x = 256
    scene.render.tile_y = 256
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'GPU'




