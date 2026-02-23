import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { FolderGit2, Globe } from 'lucide-react'
import { LegionProjectList } from '@/components/projects/LegionProjectList'
import { ProjectList } from '@/components/ProjectList'

export function ProjectsPage() {
  return (
    <div className="page-content">
      <div className="flex items-center gap-3 mb-6">
        <FolderGit2 className="w-8 h-8 text-primary" />
        <h1 className="page-title">Projects</h1>
      </div>

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
