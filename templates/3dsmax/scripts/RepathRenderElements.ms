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
indexVrayAdv = findString rendererName "V_Ray_Adv_"
indexVrayNext = findString rendererName "V_Ray_Next_"

if (indexVrayAdv == 1 or indexVrayNext == 1) then
(
    irAutoSavePath = r.adv_irradmap_autoSaveFileName
    if(irAutoSavePath != undefined) then
    (
        tokens = filterString irAutoSavePath "\\"
        filename = tokens[tokens.count]
        prefix = sysEnv.GetEnvironmentVariable "AZ_BATCH_TASK_WORKING_DIR"
        newPath = prefix + "\\images\\" + filename
        r.adv_irradmap_autoSaveFileName = newPath
    )

    irSavePath = r.adv_irradmap_saveFileName
    if(irSavePath != undefined) then
    (
        tokens = filterString irSavePath "\\"
        filename = tokens[tokens.count]
        prefix = sysEnv.GetEnvironmentVariable "AZ_BATCH_TASK_WORKING_DIR"
        newPath = prefix + "\\images\\" + filename
        r.adv_irradmap_saveFileName = newPath
    )
)
