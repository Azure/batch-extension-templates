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
indexVRay5 = findString rendererName "V_Ray_5_"

if (indexVRay5 == 1 ) then
(
    tokens = filterString irAutoSavePath "\\"
    filename = tokens[tokens.count]
    prefix = sysEnv.GetEnvironmentVariable "AZ_BATCH_TASK_WORKING_DIR"
    newPath = prefix + "\\images\\" + filename

    irAutoSavePath = r.adv_irradmap_autoSaveFileName
    if(irAutoSavePath != undefined) then
    (
        r.adv_irradmap_autoSaveFileName = newPath
    )

    irSavePath = r.adv_irradmap_saveFileName
    if(irSavePath != undefined) then
    (
        r.adv_irradmap_saveFileName = newPath
    )
)
