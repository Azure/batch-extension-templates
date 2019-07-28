sysEnv = dotNetClass "System.Environment"
rem = maxOps.GetCurRenderElementMgr()
format "\nRepath render elements"

if(rem != undefined) then
(
	format "\nFound render element manager: %" rem
	for n = 0 to (rem.NumRenderElements() - 1) do
	(
		el = rem.GetRenderElement n
		originalPath = rem.GetRenderElementFileName n
		format "\nChecking path: % - enabled: %" originalPath el.enabled

		if (el.enabled and originalPath != undefined and originalPath != "") then
		(
			format "\nFormatting path: %" originalPath
			tokens = filterString originalPath "\\"
			filename = tokens[tokens.count]
			prefix = sysEnv.GetEnvironmentVariable "AZ_BATCH_TASK_WORKING_DIR"
			newPath = prefix + "\\images\\" + filename
			format "\nUpdating render element path % => %" originalPath newPath
			rem.SetRenderElementFilename n newPath
		)
	)
)
