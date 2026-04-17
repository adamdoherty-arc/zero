import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { FolderGit2, Globe } from 'lucide-react'
import { LegionProjectList } from '@/components/projects/LegionProjectList'
import { ProjectList } from '@/components/ProjectList'

export function ProjectsPage() {
  return (
    <div className="page-content">
      <Tabs defaultValue="legion" className="w-full">
        <TabsList className="mb-4">
          <TabsTrigger value="legion" className="flex items-center gap-1.5">
            <Globe className="w-4 h-4" />
            Projects
          </TabsTrigger>
          <TabsTrigger value="local" className="flex items-center gap-1.5">
            <FolderGit2 className="w-4 h-4" />
            Local
          </TabsTrigger>
        </TabsList>

        <TabsContent value="legion">
          <LegionProjectList />
        </TabsContent>

        <TabsContent value="local">
          <ProjectList />
        </TabsContent>
      </Tabs>
    </div>
  )
}
