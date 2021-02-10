sysEnv = dotNetClass "System.Environment"

rem = maxOps.GetCurRenderElementMgr()
if(rem != undefined) then
(
	for n = 0 to (rem.NumRenderElements() - 1) do
	(
		el = rem.GetRenderElement n
		originalPath = rem.GetRenderElementFileName n
		if (el.enabled and originalPath != undefined and originalPath != "") then
		(
			tokens = filterString originalPath "\\"
			filename = tokens[tokens.count]
			prefix = sysEnv.GetEnvironmentVariable "AZ_BATCH_TASK_WORKING_DIR"
			newPath = prefix + "\\images\\" + filename
			format "\nUpdating render element path % => %" originalPath newPath
			rem.SetRenderElementFilename n newPath
		)
	)
)

r = renderers.current     
rendererName = r as string
indexVRay5 = findString rendererName "V_Ray_5"

if (indexVRay5 != undefined and indexVRay5 == 1) then
(
    prefix = sysEnv.GetEnvironmentVariable "AZ_BATCH_TASK_WORKING_DIR"
    irAutoSavePath = r.adv_irradmap_autoSaveFileName
    if(irAutoSavePath != undefined and irAutoSavePath != "" ) then
    (
        tokens = filterString irAutoSavePath "\\"
        filename = tokens[tokens.count]
        newPath = prefix + "\\images\\" + filename
        r.adv_irradmap_autoSaveFileName = newPath
    )

    irSavePath = r.adv_irradmap_saveFileName
    if(irSavePath != undefined and irSavePath != "" ) then
    (
        tokens = filterString irSavePath "\\"
        filename = tokens[tokens.count]
        newPath = prefix + "\\images\\" + filename
        r.adv_irradmap_saveFileName = newPath
    )
)
